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
 registerHooks({resolve(spec,ctx,next){if(ctx.parentURL===file('static/twin/editor/editor.js')&&!['./api.js','./history.js','./lighting.js','./edit_queue.js','./local_ops.js','./icons.js','./steps.js','./dock.js'].includes(spec))return {url:stubs,shortCircuit:true};return next(spec,ctx);}});
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
 for(const button of el('editor-toolbar').querySelectorAll('button[data-editor-icon]')) {
  const was=button.getAttribute('aria-pressed');button.setAttribute('aria-pressed','true');
  assert.equal(button.querySelector('svg').getAttribute('stroke'),'currentColor',button.id);
  assert.equal(button.querySelector('svg').getAttribute('fill'),'none',button.id);button.setAttribute('aria-pressed',was);
 }
 assert.equal(el('editor-house-name').textContent,'Our house');
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
