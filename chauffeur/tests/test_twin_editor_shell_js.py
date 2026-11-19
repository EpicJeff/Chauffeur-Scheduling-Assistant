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


def test_dock_homes(p):
    for tab in ['scene', 'layers', 'library', 'argyle']:
        assert p.inside(p.by_id('dock-pane-' + tab), 'editor-dock')
        assert any(n['attrs'].get('data-dock-tab') == tab for n in p.nodes)
    for id, home in [('editor-floors', 'dock-pane-scene'), ('library-panel', 'dock-pane-library'),
                     ('editor-agent', 'dock-pane-argyle'), ('piece-card', 'dock-properties'),
                     ('pause-card', 'dock-properties'), ('editor-history', 'editor-dock'),
                     ('editor-edit-timing', 'editor-history'), ('roof-choices', 'dock-properties')]:
        assert p.inside(p.by_id(id), home), (id, home)
    assert 'open' not in p.by_id('editor-history')['attrs']
    for id in ['properties-back', 'properties-crumbs', 'dock-splitter', 'layer-sheet', 'layer-grade']:
        p.by_id(id)
    print('  ok dock tab, Properties, Layers and folded History homes')


def test_css_contract(p):
    css = (ROOT / 'static/twin/editor/editor.css').read_text(encoding='utf-8')
    source = (ROOT / 'templates/house_editor.html').read_text(encoding='utf-8')
    selected = re.search(r'--twinSelected:\s*([^;]+)', source)[1]
    ink = re.search(r'--twinSelectedText:\s*([^;]+)', source)[1]
    assert selected != ink
    # This selector must follow the transparent icon-button rule, including
    # hover/focus. It is the class contract for ALL toolbar tools, not Select alone.
    selector = '#editor-toolbar button[data-editor-icon][aria-pressed="true"]'
    pos = css.rindex(selector)
    declaration = css[pos:css.index('}', pos)]
    assert 'background: var(--twinSelected)' in declaration
    assert 'color: var(--twinSelectedText)' in declaration
    assert pos > css.index('#editor-toolbar button[data-editor-icon],')
    for name in LABELS:
        assert p.by_id('rail-' + name)['attrs']['data-editor-icon'] == name
    scene = re.findall(r'#editor-scene\s*\{([^}]+)\}', css)[-1]
    assert 'inset: var(--editor-header-bottom, 68px) var(--editor-dock-width) var(--editor-status-height, 52px) 0' in scene
    assert 'width: var(--editor-dock-width)' in css[css.rindex('#editor-dock {'):]
    adopted = css[css.index('#editor-dialog :is(#place-view, #houses-panel, #editor-front-door, #editor-advanced)'):]
    assert 'transform: none' in adopted[:adopted.index('}')], 'adopted Houses must shed its old translate(-50%, -50%)'
    print('  ok every pressed icon has contrasting ink/background; canvas reserves exactly dock width')


DRIVER = r"""
let passed=0;
const test=async(name,fn)=>{try{await fn();passed++;console.log('  ok '+name);}catch(e){console.error('  FAIL '+name+'\n'+e.stack);process.exitCode=1;}};
const el=id=>document.getElementById(id);
globalThis.fetch=window.fetch=async url=>({ok:true,status:200,text:async()=>String(url).endsWith('/imports')?'[]':JSON.stringify({materials:[],items:[],imports:[],limit_mb:50,unpacked_limit_mb:200})});
// The actual Library runs here; only its thumbnail WebGL renderer is a CPU
// double. All domain modules use the vendored geometry and real DOM events.
const rendererModule='data:text/javascript,'+encodeURIComponent(`export * from '${file('static/vendor/three-r187/three.module.js')}';
 export class WebGLRenderer {constructor({canvas}){this.domElement=canvas;}setSize(){}setPixelRatio(){}render(){}dispose(){}forceContextLoss(){}}`);
registerHooks({resolve(spec,ctx,next){if(spec==='three'&&ctx.parentURL===file('static/twin/editor/library.js'))return {url:rendererModule,shortCircuit:true};return next(spec,ctx);}});
// Use the rendered Jinja tree, so a runtime lookup sees the moved real node.
const nodes=config.nodes.map(n=>document.createElement(n.tag));
config.nodes.forEach((n,i)=>{for(const [k,v] of Object.entries(n.attrs))nodes[i].setAttribute(k,v??'');
 if(!['script','style'].includes(n.tag))nodes[i].textContent=n.text;
 (n.parent===null?document.body:nodes[n.parent]).append(nodes[i]);});
await test('one centred dialog adopts existing nodes, replaces its predecessor, traps focus and consumes Esc first',async()=>{
 const {mountDialogs,openDialog,closeDialog}=await import(file('static/twin/editor/dialog.js'));
 const abort=new AbortController();mountDialogs({signal:abort.signal});
 const houses=el('houses-panel'),materials=el('house-materials'),parent=houses.parentElement;
 el('editor-houses').focus();openDialog('houses-panel',{title:'Houses'});
 assert.equal(houses.hidden,false);assert.ok(el('editor-dialog').contains(houses));
 openDialog('house-materials',{title:'House materials'});
 assert.equal(houses.hidden,true);assert.equal(materials.hidden,false);assert.equal(el('editor-dialog').hidden,false);
 let lower=0;const listener=()=>lower++;document.addEventListener('keydown',listener);
 el('editor-dialog-close').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 assert.equal(lower,0);assert.equal(el('editor-dialog').hidden,true);assert.equal(materials.hidden,true);
 assert.equal(document.activeElement,el('editor-menu').querySelector('summary'),'closed menu actions restore focus to its summary');
 assert.equal(houses.parentElement,parent);assert.equal(el('houses-panel'),houses);
 document.removeEventListener('keydown',listener);
 openDialog('houses-panel',{title:'Houses'});
 const last=el('houses-list'),input=document.createElement('input');last.append(input);input.focus();
 input.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true}));
 assert.equal(document.activeElement,el('editor-dialog-close'));
 el('editor-dialog-close').dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true,cancelable:true}));
 assert.equal(document.activeElement,input);input.remove();closeDialog();abort.abort();
});
await test('real Houses and Your place entry points share the dialog host; setup retains one accessible tab per step',async()=>{
 const {mountDialogs}=await import(file('static/twin/editor/dialog.js')),{mountHouses}=await import(file('static/twin/editor/houses.js')),
  {createPlace}=await import(file('static/twin/editor/place.js')),{createSteps}=await import(file('static/twin/editor/steps.js'));
 const abort=new AbortController(),dialogs=mountDialogs({signal:abort.signal});
 mountHouses({dialogs,signal:abort.signal,history:{},canLoad:()=>true,api:{request:async()=>({saves:[]})}});
 await press(el('editor-houses'));assert.equal(dialogs.current(),'houses-panel');
 assert.match(el('houses-status').textContent,/No saved houses/);
 dialogs.openDialog('house-materials',{title:'House materials'});assert.equal(el('houses-panel').hidden,true);
 const sheets={sources:[],page_roles:[],kinds:[],place:{buildings:[],lot:{}}};let place;
 const steps=createSteps(el('place-steps'),{state:{model:samplePlan(),sheets},tabs:true,onOpen:name=>place.open(name)});
 place=createPlace({dialogs,steps,getSheets:()=>sheets,getPlan:samplePlan,getLink:()=>null,canEdit:()=>true,
  request:async()=>({}),panel:{message(){}},onClose:()=>steps.close()});
 place.sync(sheets,{});place.open('Your files');assert.equal(dialogs.current(),'place-view');
 assert.equal(el('house-materials').hidden,true);assert.equal(el('editor-dialog-title').textContent,'Your place');
 assert.equal(el('place-steps').getAttribute('role'),'tablist');
 assert.equal(el('place-steps').querySelectorAll('[role="tab"]').length,5);
 for(const name of ['Your files','Your lot','Build','Link to Home Assistant']) {
  const tab=el('place-steps').querySelector(`[data-step="${name}"]`);await press(tab);
  assert.equal(tab.getAttribute('aria-selected'),'true');assert.equal(el('place-view').dataset.stepPanel,name);
 }
 place.sync(sheets,{buildState:{state:'running'}});assert.equal(el('place-steps').querySelector('button').disabled,false);
 const placeNode=el('place-view');el('place-close').click();assert.equal(dialogs.current(),null);assert.equal(el('place-view'),placeNode);
 abort.abort();
});
await test('canvas context menu preserves selection until action; wall split uses hit point; yard object actions reuse transforms',async()=>{
 const {createSceneTools}=await import(file('static/twin/editor/scene_tools.js'));
 const {mountDialogs,openDialog}=await import(file('static/twin/editor/dialog.js'));
 globalThis.ResizeObserver=class {observe(){}disconnect(){}unobserve(){}};
 const abort=new AbortController();mountDialogs({signal:abort.signal});const {view,canvas}=dockRig(),plan=samplePlan(),ops=[];
 plan.site.planting=[{id:'tree',kind:'tree',x:15,y:15,scale:1}];
 let hit={kind:'wall',id:'wall',building:'b',point:[2.58*.3048,8*.3048,-3.44*.3048],distance:1};
 view.pickAll=()=>[hit];view.setSelection=()=>{};view.setRoom=()=>{};view.setEditableLevel=async()=>{};
 const tools=createSceneTools({view,getPlan:()=>plan,getModel:()=>plan,getKit:()=>({}),getSheets:()=>({}),
  op:async operation=>ops.push({operation,selection:tools.selected()}),edit:async()=>{},canEdit:()=>true,signal:abort.signal,panel:{clearSelection(){}}});
 const right=()=>canvas.dispatchEvent(new MouseEvent('contextmenu',{clientX:333,clientY:222,bubbles:true,cancelable:true}));
 const labels=()=>el('editor-context-menu').querySelectorAll('button').map(b=>b.textContent);
 tools.select({pieceId:'chair',buildingId:'b'});right();assert.equal(tools.selected().pieceId,'chair');
 assert.deepEqual(labels(),['Select','Split wall here','Add door here','Add window here','Delete']);
 await press(el('editor-context-menu').querySelectorAll('button')[1]);
 assert.deepEqual(ops[0].operation,{op:'split_wall',building:'b',wall:'wall',at:4.25});
 assert.equal(ops[0].selection.pieceId,'wall');
 right();await press(el('editor-context-menu').querySelectorAll('button')[2]);
 assert.deepEqual({...ops.at(-1).operation,at:4.3},{op:'add_opening',building:'b',wall:'wall',kind:'door',width:3,at:4.3});
 assert.ok(Math.abs(ops.at(-1).operation.at-4.3)<1e-9);
 right();await press(el('editor-context-menu').querySelectorAll('button')[3]);assert.equal(ops.at(-1).operation.kind,'window');
 hit={kind:'planting',id:'tree',distance:1};right();assert.equal(tools.selected().pieceId,'wall');
 assert.deepEqual(labels(),['Select','Move','Turn','Scale','Mirror left-right','Mirror front-back','Delete']);
 await press(el('editor-context-menu').querySelectorAll('button')[4]);
 assert.deepEqual(ops.at(-1).operation,{op:'set_object',list:'planting',index:0,properties:{mirror_x:true}});
 openDialog('houses-panel',{title:'Houses'});right();
 document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 assert.equal(el('editor-context-menu').hidden,true);assert.equal(el('editor-dialog').hidden,false);
 document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 assert.equal(el('editor-dialog').hidden,true);assert.equal(tools.selected().pieceId,'tree');
 for(const [index,name] of [[1,'move'],[2,'rotate'],[3,'scale']]) {
  right();await press(el('editor-context-menu').querySelectorAll('button')[index]);
  assert.equal(el('rail-'+name).getAttribute('aria-pressed'),'true');
 }
 // An overlay consumes Escape before the armed split tool or selection can change.
 hit={kind:'wall',id:'wall',building:'b',distance:1};tools.select(hit);
 await press(el('piece-card').querySelectorAll('button').find(b=>b.textContent==='Split wall'));
 openDialog('houses-panel',{title:'Houses'});
 document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 assert.match(el('editor-status').textContent,/Click the wall where it should split/);assert.equal(tools.selected().pieceId,'wall');
 document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 assert.equal(tools.selected().pieceId,'wall');assert.doesNotMatch(el('editor-status').textContent,/Click the wall where it should split/);
 tools.drawFloors();const floor=el('editor-floors').querySelector('[data-floor="b:L1"]');
 floor.dispatchEvent(new MouseEvent('contextmenu',{clientX:900,clientY:200,bubbles:true,cancelable:true}));
 assert.deepEqual(labels(),['Show','Hide','Choose']);
 await press(el('editor-context-menu').querySelectorAll('button')[2]);assert.equal(tools.selected().pieceId,'L1');
 let cancelled=0,typed=0;tools.delegate({pointerArmedDown(){view.controls.enabled=false;return true;},pointerUp(_event,cancel){if(cancel)cancelled++;return true;},key(event){if(event.key!=='2')return false;typed++;return 'commit';}});
 canvas.dispatchEvent(new PointerEvent('pointerdown',{button:0,pointerId:92,clientX:20,clientY:20,bubbles:true,cancelable:true}));
 openDialog('houses-panel',{title:'Houses'});
 el('editor-dialog-close').dispatchEvent(new KeyboardEvent('keydown',{key:'2',bubbles:true,cancelable:true}));assert.equal(typed,0);
 document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 assert.equal(cancelled,0);assert.equal(view.controls.enabled,false);assert.equal(tools.selected().pieceId,'L1');
 document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 assert.equal(cancelled,1);assert.equal(view.controls.enabled,true);assert.equal(tools.selected().pieceId,'L1');
 abort.abort();canvas.remove();
});
await test('dock preserves nodes, separates tabs from Properties, gives tool options priority and resizes',async()=>{
 const {createDock}=await import(file('static/twin/editor/dock.js'));
 const dock=createDock({host:el('editor-dock')});
 const piece=el('piece-card'), original=piece, options=el('draw-options');
 let backed=0,resized=0;dock.onResize(()=>resized++);
 dock.properties.render(piece,{crumbs:['Ground floor','Kitchen','Wall'],back:()=>backed++});
 dock.show('library');assert.equal(el('dock-pane-library').hidden,false);assert.equal(el('dock-pane-scene').hidden,true);
 assert.ok(el('dock-properties').contains(piece));assert.equal(piece,original);assert.equal(piece.hidden,false);
 await press(el('properties-back'));assert.equal(backed,1);
 dock.properties.render(options,{crumbs:['Draw wall'],tool:true});
 dock.properties.render(piece,{crumbs:['Ground floor','Kitchen','Wall'],reveal:false});
 assert.equal(options.parentElement.hidden,false);assert.equal(piece.parentElement.hidden,true);
 dock.properties.clear(options);assert.equal(piece.parentElement.hidden,false);
 assert.match(el('properties-crumbs').textContent,/Ground floor.*Kitchen.*Wall/);
 el('dock-splitter').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));
 assert.ok(resized>0);const before=resized;window.dispatchEvent(new Event('resize'));assert.equal(resized,before+1);
 el('editor-dock')._rect={left:1036,top:0,width:364,height:1000};
 const splitter=el('dock-splitter');splitter.dispatchEvent(new PointerEvent('pointerdown',{button:0,pointerId:22}));
 splitter.dispatchEvent(new PointerEvent('pointermove',{clientY:900,pointerId:22}));assert.equal(splitter.getAttribute('aria-valuenow'),'70');
 splitter.dispatchEvent(new PointerEvent('pointermove',{clientY:50,pointerId:22}));assert.equal(splitter.getAttribute('aria-valuenow'),'20');
 splitter.dispatchEvent(new PointerEvent('pointerup',{pointerId:22}));assert.equal(splitter.hasPointerCapture(22),false);
 dock.properties.clear();assert.match(el('dock-properties').textContent,/Nothing selected/);
 const removed=document.createElement('aside');dock.properties.render(removed,{crumbs:['Temporary card']});removed.remove();
 dock.dispose();assert.equal(removed.isConnected,false);assert.equal(el('piece-card'),original);
});
function dockRig() {
 const canvas=document.createElement('canvas');el('editor-scene').append(canvas);
 const controls=new EventTarget();controls.enabled=true;controls.target=new THREE.Vector3();controls.update=()=>{};
 const view={renderer3:{domElement:canvas},scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(45,1.4,.1,1000),controls,
  state:{view:'b:L1',camera:'top'},groups:{site:new THREE.Group(),levels:{}},render(){},pick:()=>null,
  floorAt:(x,y)=>[x,y],screenOfFloor:(x,y)=>[x*10,y*10],setView(value){this.state.view=value;},showLevels(){},setCamera(){}};
 view.camera.position.set(0,50,.01);view.camera.lookAt(0,0,0);view.camera.updateMatrixWorld(true);
 return {view,canvas};
}
function samplePlan() {
 return {buildings:[{id:'b',name:'Our house',position:[0,0],rotation:0,
  levels:[{id:'L1',name:'Ground floor',elevation:0,ceiling:9},{id:'L2',name:'Upstairs',elevation:10,ceiling:9}],
  joints:[{id:'j1',at:[0,0],level:'L1'},{id:'j2',at:[6,8],level:'L1'}],
  walls:[{id:'wall',from:[0,0],to:[6,8],joints:['j1','j2'],height:9,thickness:.5,level:'L1'}],
  rooms:[{id:'room',name:'Kitchen',level:'L1',walls:['wall'],polygon:[[0,0],[12,0],[12,12],[0,12]]}],
  openings:[{id:'door',kind:'door',wall:'wall',width:3,sill:0,head:7,at:2,level:'L1'}],
  items:[{id:'chair',kind:'furniture',host:{floor:'room',u:.5,v:.5},rotation:0,scale:1}],
  anchors:[{id:'anchor',kind:'light',host:{floor:'room',u:.2,v:.2}}, {id:'device',kind:'light',device:'d',host:{floor:'room',u:.3,v:.3}}],
  roofs:[],roof:{sections:[]}}],site:{lot:[[0,0],[40,0],[40,40],[0,40]],
  terraces:[{id:'pad',polygon:[[0,0],[10,0],[10,10],[0,10]],height:1,blend:2}],
  beds:[{id:'bed',polygon:[[0,0],[5,0],[5,5],[0,5]],material:'mulch'}],
  hardscape:[{id:'path',kind:'path',points:[[0,0],[10,0]],width:3,pavers:{layout:'grid'}}]},
  light_fixtures:{'light.kitchen':[{id:'spot',shape:'spot',ref:'floor',building:'b',level:'L1',at:[2,2,8],aim:[2,2,0],cone_deg:45}]},
  effect_fixtures:[{id:'effect',type:'fire',shape:'point',ref:'ground',at:[1,1,0],size_min:.1,size_max:1}]};
}
await test('real cards and shelves use Properties; wall Length moves only joints[1] and Back walks room/floor',async()=>{
 const {createDock}=await import(file('static/twin/editor/dock.js')),{createCards}=await import(file('static/twin/editor/cards.js'));
 const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));
 window.twinObjectSchema=JSON.parse(readFileSync(root+'/static/twin/object_schema.json'));
 let plan=samplePlan(),selection=null;const operations=[],alerts=[];
 window.showGlobalAlert=text=>alerts.push(text);
 const dock=createDock({host:el('editor-dock')}),card=el('piece-card');
 let cards;const select=value=>{selection=value;cards.draw(value);};
 cards=createCards({dock,getPlan:()=>plan,getKit:()=>({}),getSelection:()=>({room:'room'}),getLabel:()=> 'Kitchen wall',
  canEdit:()=>true,select,ask(){},edit:async o=>operations.push(o),op:async o=>{operations.push(o);plan=applyLocal(plan,o).plan;}});
 for(const [id,building] of [['wall','b'],['room','b'],['door','b'],['chair','b'],['anchor','b'],['bed',null],['path',null],['b','b']]) {
  select({pieceId:id,buildingId:building});assert.equal(card.hidden,false,id);assert.ok(el('dock-properties').contains(card),id);
  assert.equal(card.parentElement.hidden,false,id);
 }
 select({pieceId:'path',buildingId:null});assert.ok(card.querySelector('[aria-label="Surface"]'),'paver shelf survives');
 select({pieceId:'wall',buildingId:'b'});
 assert.match(el('properties-crumbs').textContent,/Ground floor > Kitchen > Wall/);
 const length=card.querySelectorAll('label').find(n=>n.firstChild?.textContent==='Length').querySelector('input');
 assert.equal(length.value,'10\'-0"');length.value='15\'-0"';length.dispatchEvent(new Event('change'));
 length.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',cancelable:true}));await cards.queue(()=>{});await wait(10);
 assert.deepEqual(operations,[{op:'move_joint',building:'b',joint:'j2',to:[9,12]}]);
 assert.deepEqual(plan.buildings[0].joints[0].at,[0,0]);
 await press(el('properties-back'));assert.equal(selection.pieceId,'room');
 await press(el('properties-back'));assert.equal(selection.pieceId,'L1');assert.deepEqual(alerts,[]);
 dock.properties.clear();card.hidden=true;dock.dispose();
});
await test('device Fixtures breadcrumb, back to device, line options and aim live in Properties',async()=>{
 const {createDock}=await import(file('static/twin/editor/dock.js')),{createFixtureEditor}=await import(file('static/twin/editor/fixtures.js'));
 const dock=createDock({host:el('editor-dock')}),abort=new AbortController(),{view}=dockRig(),plan=samplePlan();
 let selected={pieceId:'device',buildingId:'b'};
 const tools={select:value=>selected=value,selected:()=>selected,selection:()=>({building:'b',room:'room'}),setTool(){}};
 const fixtures=createFixtureEditor({dock,view,tools,library:{surfaceAt:()=>null,ground:e=>[e.clientX,e.clientY]},getPlan:()=>plan,op:async()=>{},canEdit:()=>true,signal:abort.signal});
 const device={device_id:'d',name:'Kitchen lamp',kind:'light',entity_id:'light.kitchen'};
 fixtures.showDevice(device);assert.equal(el('properties-crumbs').textContent,'Ground floor > Kitchen > Kitchen lamp > Fixtures');
 await press(el('properties-back'));assert.deepEqual(selected,{pieceId:'device',buildingId:'b'});
 // A device placed directly on a room surface has a parent HA section too,
 // even though it has no selectable anchor piece.
 plan.buildings[0].devices=[{id:'surface-device',device:'surface',host:{floor:'room',u:.5,v:.5}}];
 tools.haLink={anchorSection:device=>{const node=document.createElement('section');node.textContent=device.device;return node;}};
 fixtures.showDevice({...device,device_id:'surface'});await press(el('properties-back'));
 assert.equal(el('properties-crumbs').textContent,'Ground floor > Kitchen > Kitchen lamp');
 assert.ok(el('piece-card').textContent.includes('surface'));await press(el('properties-back'));assert.equal(selected.pieceId,'room');
 fixtures.showDevice(device);const add=el('piece-card').querySelectorAll('button').find(b=>b.textContent==='Add line fixture');await press(add);
 assert.ok(el('device-options').querySelector('[aria-label="Snap points"]'));
 assert.ok(el('device-options').querySelector('[aria-label="Facing"]'));
 assert.equal(el('device-options').parentElement.hidden,false);
 assert.ok(el('device-tools').querySelectorAll('button').some(b=>b.textContent==='Finish'));
 fixtures.cancel();fixtures.aim('light.kitchen',plan.light_fixtures['light.kitchen'][0]);
 assert.ok(el('device-options').querySelector('[aria-label="Cone (degrees)"]'));
 fixtures.cancel();fixtures.showEffect('effect');assert.ok(el('dock-properties').contains(el('piece-card')));
 abort.abort();dock.dispose();
});
await test('terrain drafts, pads, Grade and lot/building entry points use the dock',async()=>{
 const {createDock}=await import(file('static/twin/editor/dock.js')),{createTerrainTools}=await import(file('static/twin/editor/terrain_tools.js')),
  {createLotTools}=await import(file('static/twin/editor/lot_tools.js'));
 const dock=createDock({host:el('editor-dock')}),abort=new AbortController(),{view}=dockRig(),plan=samplePlan();
 let selection={};const tools={select:value=>{selection=value||{};},setTool(){},selection:()=>selection};
 const terrain=createTerrainTools({dock,view,tools,getPlan:()=>plan,getKit:()=>({}),op:async()=>{},canEdit:()=>true,signal:abort.signal});
 terrain.startDrawing('path',{preset:'paver_path',width:3,corner:'mitred'});
 assert.ok(el('dock-properties').contains(el('terrain-card')));assert.equal(el('terrain-card').parentElement.hidden,false);
 assert.ok(el('terrain-card').textContent.includes('Width (ft)'));assert.ok(el('draw-tools').textContent.includes('Finish'));
 terrain.cancel();assert.equal(el('draw-tools').hidden,true);
 terrain.choose('terraces','pad');assert.ok(el('terrain-card').textContent.includes('Pad height (ft)'));
 await press(el('layer-grade'));assert.equal(el('layer-grade').getAttribute('aria-pressed'),'true');
 assert.ok(el('scene-yard').textContent.includes('Pad 1'));terrain.cancel();
 const lot=createLotTools({dock,view,getPlan:()=>plan,getSheets:()=>({place:{buildings:[{id:'b',name:'Our house'}],lot:{}}}),
  getSelection:()=>selection,select:value=>selection=value?{...value,kind:'building'}:{},pauses:{lotPlacement:()=>null},op:async()=>{},reload:async()=>{},canEdit:()=>true,signal:abort.signal});
 lot.showLot();assert.match(el('properties-crumbs').textContent,/Lot/);
 const card=el('dock-properties').querySelector('[aria-label="Lot placement"]');assert.ok(card);
 await press(el('scene-lot').querySelectorAll('button').find(b=>b.textContent==='Our house'));
 assert.match(el('properties-crumbs').textContent,/Our house/);assert.ok(card.textContent.includes('Turn 90 degrees'));
 lot.drawFootprint('new-building');assert.match(el('properties-crumbs').textContent,/Draw footprint/);
 const cancel=el('draw-tools').querySelectorAll('button').filter(b=>b.textContent==='Cancel drawing'&&!b.hidden);
 assert.equal(cancel.length,1);await press(cancel[0]);assert.equal(el('draw-tools').hidden,true);assert.equal(el('draw-cancel').hidden,false);
 lot.drawFootprint('new-building');await press(card.querySelectorAll('button').find(b=>b.textContent==='Close'));
 assert.equal(lot.pointerArmedDown({button:0}),false);assert.equal(el('draw-tools').hidden,true);
 abort.abort();dock.dispose();
});
await test('draw, stair, roof and device placement options take Properties and cancel cleanly',async()=>{
 const {createDock}=await import(file('static/twin/editor/dock.js')),{createDraw}=await import(file('static/twin/editor/draw.js')),
  {createRoofTools}=await import(file('static/twin/editor/roof_tools.js')),{createDevicePlacement}=await import(file('static/twin/editor/device_placement.js'));
 const dock=createDock({host:el('editor-dock')}),abort=new AbortController(),{view}=dockRig(),plan=samplePlan();
 const tools={setTool(){},select(){},selection:()=>({}),selectedRooms:()=>null,haLink:{setPlacement(){}},
  floor:()=>({key:'b:L1',building:plan.buildings[0],level:plan.buildings[0].levels[0]})},panel={message(){}};
 const draw=createDraw({dock,view,tools,getPlan:()=>plan,op:async()=>{},gesture:fn=>fn(),canEdit:()=>true,signal:abort.signal,panel});
 await press(el('rail-draw-wall'));assert.equal(el('draw-options').parentElement.hidden,false);assert.match(el('properties-crumbs').textContent,/Draw wall/);
 assert.equal(el('draw-note').closest('#editor-statusbar'),el('editor-statusbar'));await press(el('draw-cancel'));
 await press(el('rail-add-stair'));assert.equal(el('piece-card').parentElement.hidden,false);assert.ok(el('piece-card').textContent.includes('To level'));
 draw.cancel();
 const roof=createRoofTools({dock,view,tools,getPlan:()=>plan,op:async()=>{},canEdit:()=>true,signal:abort.signal,panel,cancelDrawing:draw.cancel});
 await press(el('rail-roof'));assert.equal(el('roof-options').parentElement.hidden,false);assert.equal(el('roof-choices').hidden,false);
 await press(el('roof-draw'));assert.match(el('properties-crumbs').textContent,/Draw roof area/);roof.cancel();
 const placement=createDevicePlacement({dock,view,tools,library:{surfaceAt:()=>null,ground:()=>[0,0]},getPlan:()=>plan,op:async()=>{},canEdit:()=>true,signal:abort.signal,prepare(){}});
 placement.arm({device_id:'d',name:'Kitchen lamp'},'wall');assert.match(el('properties-crumbs').textContent,/Kitchen lamp > Place device/);
 assert.equal(el('device-options').parentElement.hidden,false);await press(el('device-cancel'));assert.equal(el('device-tools').hidden,true);
 abort.abort();dock.dispose();
});
await test('Library opens by tab, rail and material Change without clearing scene selection; Argyle names it',async()=>{
 const {createDock}=await import(file('static/twin/editor/dock.js')),{createLibrary}=await import(file('static/twin/editor/library.js')),
  {createPanel}=await import(file('static/twin/editor/panel.js'));
 const dock=createDock({host:el('editor-dock')}),abort=new AbortController(),{view}=dockRig(),plan=samplePlan();
 let selection={pieceId:'wall',buildingId:'b'};
 let reads=0;const previousFetch=window.fetch;globalThis.fetch=window.fetch=async(...args)=>{reads++;return previousFetch(...args);};
 dock.properties.render(el('piece-card'),{crumbs:['Kitchen','Wall']});
 const library=createLibrary({dock,view,kit:{},getPlan:()=>plan,tools:{select:value=>{selection=value;},selected:()=>selection,selection:()=>({}),handles:()=>[]},
  op:async()=>{},canEdit:()=>true,signal:abort.signal});
 await press(el('rail-library'));assert.equal(el('dock-pane-library').hidden,false);assert.deepEqual(selection,{pieceId:'wall',buildingId:'b'});
 assert.equal(el('piece-card').parentElement.hidden,false);
 dock.show('scene');await press(el('dock-tab-library'));assert.equal(dock.current(),'library');
 dock.show('scene');await library.pick({label:'wall face'});assert.equal(dock.current(),'library');assert.equal(el('library-panel').hidden,false);
 const before=reads;dock.show('scene');window.dispatchEvent(new Event('focus'));await wait(10);assert.equal(reads,before);
 dock.show('library');await wait(10);assert.ok(reads>before);
 const panel=createPanel({dock,afterSay:async()=>{},acceptPause:async()=>false});
 el('editor-message').setSelectionRange=(start,end)=>{el('editor-message').selectionStart=start;el('editor-message').selectionEnd=end;};
 panel.focusSelection(selection,'Kitchen wall');assert.equal(dock.current(),'argyle');assert.equal(el('editor-message').value,'About Kitchen wall: ');
 assert.equal(el('editor-message').selectionEnd,el('editor-message').value.length);
 assert.deepEqual(selection,{pieceId:'wall',buildingId:'b'});panel.dispose();abort.abort();dock.dispose();globalThis.fetch=window.fetch=previousFetch;
});
await test('material drag still opens its own scope menu at the drop point; Library menus and import settings retain their actions',async()=>{
 const {createLibrary}=await import(file('static/twin/editor/library.js')),{mountDialogs}=await import(file('static/twin/editor/dialog.js')),
  {createContextMenu}=await import(file('static/twin/editor/context_menu.js'));
 const abort=new AbortController(),dialogs=mountDialogs({signal:abort.signal}),{view,canvas}=dockRig(),plan=samplePlan();
 const previous=window.fetch,elementAt=document.elementFromPoint;const ops=[];
 globalThis.fetch=window.fetch=async url=>({ok:true,status:200,text:async()=>String(url).endsWith('/imports')?'[]':JSON.stringify({
  materials:[{id:'stone',name:'Stone',thumbnail_url:'/stone.png'}],items:[],imports:[{id:'import-chair',name:'Chair',thumbnail_url:'/chair.png'}]})});
 document.elementFromPoint=()=>canvas;view.pick=()=>({kind:'room',id:'room',building:'b',part:'floor'});
 el('library-panel').hidden=true;
 const library=createLibrary({dialogs,createMenu:createContextMenu,view,kit:{},getPlan:()=>plan,tools:{selection:()=>({}),handles:()=>[]},
  op:async operation=>ops.push(operation),canEdit:()=>true,signal:abort.signal});
 await press(el('rail-library'));const tile=el('library-entries').querySelector('[data-material="stone"]');assert.ok(tile);
 tile.dispatchEvent(new MouseEvent('contextmenu',{clientX:900,clientY:250,bubbles:true,cancelable:true}));
 assert.deepEqual(el('editor-context-menu').querySelectorAll('button').map(b=>b.textContent),['Edit in Library']);
 document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 tile.dispatchEvent(new PointerEvent('pointerdown',{button:0,pointerId:78,clientX:50,clientY:60,bubbles:true,cancelable:true}));
 document.dispatchEvent(new PointerEvent('pointerup',{pointerId:78,clientX:500,clientY:400,bubbles:true,cancelable:true}));
 const chooser=el('material-chooser');assert.ok(chooser);assert.equal(chooser.style.left,'500px');assert.equal(chooser.style.top,'400px');
 assert.equal(chooser.getAttribute('role'),'group');assert.equal(dialogs.current(),null);assert.equal(el('editor-context-menu').hidden,true);
 assert.ok(chooser.querySelectorAll('button').some(b=>b.textContent==='This room'));
 await press(chooser.querySelector('button'));assert.equal(ops.length,1);assert.equal(chooser.isConnected,false);
 const settings=el('library-import-settings');await press(settings.querySelector('summary'));
 assert.equal(dialogs.current(),'library-import-settings-content');assert.equal(el('library-import-settings'),settings);
 assert.ok(el('editor-dialog').contains(el('library-import-limit')));dialogs.closeDialog();
 await press(el('library-panel').querySelector('[data-library-tab="items"]'));
 const imported=el('library-entries').querySelector('[data-item="import-chair"]');
 imported.dispatchEvent(new MouseEvent('contextmenu',{clientX:900,clientY:250,bubbles:true,cancelable:true}));
 assert.deepEqual(el('editor-context-menu').querySelectorAll('button').map(b=>b.textContent),['Rename Chair','Delete Chair']);
 abort.abort();canvas.remove();globalThis.fetch=window.fetch=previous;document.elementFromPoint=elementAt;
});
await test('check queue uses Properties and forced edit timing appears inside folded History',async()=>{
 const {createDock}=await import(file('static/twin/editor/dock.js')),{createChecks}=await import(file('static/twin/editor/checks.js')),
  {mountEditTiming}=await import(file('static/twin/edit_timing.js'));
 const dock=createDock({host:el('editor-dock')}),abort=new AbortController(),{view}=dockRig(),plan=samplePlan();
 let walk=null;const checks=createChecks(view,{dock,api:{request:async()=>{},report:e=>{throw e;}},getBuild:()=>null,
  getModel:()=>({...plan,buildings:[{...plan.buildings[0],flags:[{text:'Check the wall',level:'L1'}]}]}),getPlan:()=>plan,
  panel:{checks(count,show){walk=show;}},tools:{},canEdit:()=>true,signal:abort.signal,flags:{dismiss(){},review(){}}});
 walk();assert.equal(el('check-card').parentElement.hidden,false);assert.ok(el('dock-properties').contains(el('check-card')));
 checks.dismiss();assert.equal(el('check-card').hidden,true);
 mountEditTiming({toggle:el('menu-edit-timing'),overlay:el('editor-edit-timing'),send:el('menu-send-timing'),force:true,
  signal:abort.signal,post:async()=>{},report:e=>{throw e;}});
 assert.equal(el('editor-timing-section').hidden,false);assert.ok(el('editor-history').contains(el('editor-edit-timing')));
 assert.equal(el('editor-edit-timing').hidden,false);
 assert.equal(el('editor-history').open,true);
 abort.abort();dock.dispose();
});
await test('paused review adopts the original controls into Properties and accepts through their real handler',async()=>{
 const {createDock}=await import(file('static/twin/editor/dock.js')),{createChecks}=await import(file('static/twin/editor/checks.js')),
  {createPauses}=await import(file('static/twin/editor/pauses.js'));
 const dock=createDock({host:el('editor-dock')}),abort=new AbortController(),{view}=dockRig(),plan=samplePlan();
 view.plan=plan;view.groups.levels['b:L1']=new THREE.Group();
 const build={id:'build',state:'paused',part:'b',steps:[{id:'s',level:'L1',label:'Kitchen outline'}],pause:{kind:'scale_outline',step:'s',dimension_ft:10,size_ft:[10,10],registration:{origin_px:[0,0],scale:1,offset:[0,0],angle:0}}};
 const answers=[],original=el('pause-accept'),originalReread=el('pause-reread'),previousFetch=window.fetch;
 globalThis.fetch=window.fetch=async(url,init)=>{answers.push(JSON.parse(init.body));return {ok:true,status:200,text:async()=> '{}'};};
 const pauses=createPauses({dock,view,getBuild:()=>build,getGhost:()=>null,getSheets:()=>({page_roles:[]}),refresh:async()=>{},preview(){},canEdit:()=>true,signal:abort.signal,guided:true});
 pauses.sync();
 const checks=createChecks(view,{dock,api:{request:async()=>{}},getBuild:()=>build,getModel:()=>plan,getPlan:()=>plan,
  panel:{checks(){}},tools:{},canEdit:()=>true,signal:abort.signal,pauses,flags:{dismiss(){},review(){}}});
 checks.show();assert.ok(el('check-card').contains(original));assert.ok(el('check-card').contains(originalReread));
 assert.ok(el('dock-properties').contains(original));assert.equal(el('check-card').parentElement.hidden,false);
 el('pause-dimension').value='20';await press(original);assert.equal(answers.length,1);assert.equal(answers[0].decision.registration.scale,2);
 checks.dismiss();assert.equal(original,el('pause-accept'));assert.equal(originalReread,el('pause-reread'));
 abort.abort();dock.dispose();globalThis.fetch=window.fetch=previousFetch;
});
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
 let build=null;const buildWrites=[];let setupBuildings=[{id:'b',name:'Our house',kind:'main_house',shell:{storeys:1,roof:'gable'}}];
 const plan={buildings:[{id:'b',name:'Our house',levels:[],walls:[],rooms:[],roofs:[]}],site:{}};
 globalThis.realCreatePlace=(await import(file('static/twin/editor/place.js'))).createPlace;
 globalThis.editorView={scene:{},state:{},dispose(){},setTime(){},setUnlit(){},rebuild:async()=>{}};
 const response=body=>({ok:true,status:200,text:async()=>JSON.stringify(body)});
 globalThis.fetch=window.fetch=async (url,init={})=>{
  const path=String(url).split('api/house/')[1];
  if(path==='editor/sheets')return response({sources:[],page_roles:[],kinds:[],place:{buildings:setupBuildings,lot:{}}});
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
  .replace('return {select,selected:', 'return {floor:()=>null,select,selected:')
  .replace('dismissed:()=>false','dismissed:()=>true')
  .replace('export const createChecks=()=>({sync(){},dismiss(){}});','export const createChecks=()=>({sync(){},dismiss(){},show(){globalThis.checkShown=true;}});')
  .replace("export const createPlace=()=>({sync(){},isOpen:()=>false});","export const createPlace=options=>{const place=globalThis.realCreatePlace(options);return {...place,open(name){globalThis.openedPlaceStep=name;place.open(name);}};};"));
 registerHooks({resolve(spec,ctx,next){if(ctx.parentURL===file('static/twin/editor/editor.js')&&!['./api.js','./history.js','./lighting.js','./edit_queue.js','./local_ops.js','./icons.js','./steps.js','./dock.js','./dialog.js','./context_menu.js','./house_materials.js'].includes(spec))return {url:stubs,shortCircuit:true};return next(spec,ctx);}});
 const bootErrors=[];window.showGlobalAlert=value=>bootErrors.push(value);
 const {boot}=await import(file('static/twin/editor/editor.js'));await boot();assert.ok(window.__editor.ready,JSON.stringify(bootErrors));
 assert.equal(el('editor-dialog-title').textContent,'Your place');assert.equal(el('place-view').hidden,false);
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
 for(const button of el('editor-toolbar').querySelectorAll('button[data-editor-icon]')) {
  const was=button.getAttribute('aria-pressed');button.setAttribute('aria-pressed','true');
  assert.equal(button.querySelector('svg').getAttribute('stroke'),'currentColor',button.id);
  assert.equal(button.querySelector('svg').getAttribute('fill'),'none',button.id);button.setAttribute('aria-pressed',was);
 }
 assert.equal(el('editor-house-name').textContent,'Our house');
 const {closeDialog}=await import(file('static/twin/editor/dialog.js'));closeDialog();
 const advanced=el('editor-advanced');await press(el('menu-advanced'));
 assert.ok(el('editor-dialog').contains(advanced));assert.match(el('advanced-plan').value,/Our house/);
 await press(el('advanced-close'));assert.equal(advanced.hidden,true);
 await press(el('properties-house-materials'));assert.equal(el('editor-dialog-title').textContent,'House materials');
 const expectedMaterials=document.createElement('div');
 (await import(file('static/twin/editor/house_materials.js'))).houseMaterialsShelf(expectedMaterials,plan.buildings[0],{getPlan:()=>plan,canEdit:()=>true,op:async()=>{}});
 assert.deepEqual(el('house-materials').querySelectorAll('[data-material-slot]').map(n=>n.dataset.materialSlot),
  expectedMaterials.querySelectorAll('[data-material-slot]').map(n=>n.dataset.materialSlot));
 await press(el('menu-settings'));assert.equal(el('house-materials').hidden,true);
 assert.ok(el('editor-dialog').contains(el('menu-reset-spend')));closeDialog();
 setupBuildings=[];plan.buildings=[];await globalThis.houseOptions.afterLoad({round:1});
 assert.equal(el('editor-front-door').hidden,false);assert.ok(el('editor-dialog').contains(el('editor-front-door')));
 assert.ok(el('editor-front-door').contains(el('editor-draw-myself')));
 document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 await window.__editor.pollNow(true);assert.equal(el('editor-dialog').hidden,true,'poll must not reopen dismissed welcome');
 await press(el('editor-add-files'));assert.equal(el('editor-dialog-title').textContent,'Your place');
 assert.equal(el('place-view').hidden,false);
 window.dispatchEvent(new Event('pagehide'));
});
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
console.log(`${passed} shell runtime checks passed`);process.exit(process.exitCode||0);
"""


if __name__ == '__main__':
    p = page()
    failed = False
    try:
        test_homes(p)
        test_dock_homes(p)
        test_css_contract(p)
    except AssertionError as e:
        print(f'  FAIL control homes: {e}')
        failed = True
    result = run(DRIVER, {'nodes': p.nodes, 'stubs': STUBS}, timeout=50)
    sys.exit(1 if failed or result else 0)
