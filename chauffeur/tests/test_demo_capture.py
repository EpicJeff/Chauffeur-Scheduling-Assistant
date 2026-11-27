"""Demo CLI and synthetic seed contracts; no browser, run as a plain script."""
from contextlib import nullcontext, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools' / 'demo_capture.py'
NAMES = ['my-day', 'plan', 'wall-board', 'twin-overview', 'twin-editor', 'twin-gutters',
         'twin-awning-editor', 'twin-awning-box-editor', 'twin-posts',
         'twin-eave-streams', 'twin-lit-models', 'twin-awning-garden', 'twin-downspout-hand', 'twin-room-focus',
         'library-models', 'twin-post-card', 'board']


class DemoCaptureTests(unittest.TestCase):
    def test_surface_guards_reject_overlays(self):
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT / 'tests'))
        from tools.demo_capture import SURFACE_STATE
        from twin_editor_dom import PRELUDE, run_node
        driver = PRELUDE + r'''
const check = new Function('return (' + input.guard + ')')();
const node = {getClientRects: () => [{}], getBoundingClientRect:()=>({top:100,bottom:140,left:1000,right:1300})};
const nodes = new Map();
document.querySelector = selector => nodes.get(selector) || null;
document.querySelectorAll = selectors => selectors.split(',').map(s=>nodes.get(s.trim())).filter(Boolean);
document.getElementById = id => nodes.get('#'+id) || null;
globalThis.getComputedStyle = el => ({visibility:'visible', display:'block', overflowY:el.overflowY || 'visible'});
window.innerHeight=900; window.innerWidth=1600;
window.Alpine = {$data: () => ({board:{tiles:[{}]}})};
window.__editor = {ready:true, selected:()=>({pieceId:'r1',buildingId:'synth-house'})};
window.__twinEditor = {selection:()=>({room:null})};
window.__twin = {
  ready:true, plan:{buildings:[{id:'synth-house', roofs:[{id:'demo-awning'}]}]}, stats:()=>({triangles:100}),
  eaves:{group:{visible:true}, data:{instances:[{}], pours:[]}},
  weather:{precip:'rain', rate:1, wetness:1},
  bake:{fresh:()=>['light.demo_floor_lamp'], models:{stats:()=>({bricks:4})}},
  state:{time:'night'},
  levels:{snapshot:()=>({level:'floor'})},
};
window.__demoGutterFrame = {run:'demo-run', spout:'demo-spout'};
for (const shot of input.shots) {
  window.__twin.state.time = shot === 'twin-lit-models' ? 'night' : 'auto';
  window.__editor.selected = () => ({pieceId:shot.startsWith('twin-awning-')?'demo-awning':shot==='twin-posts'?'front-porch':shot==='twin-room-focus'?'rm1':'r1',buildingId:'synth-house'});
  window.__twinEditor.selection = () => ({room: shot === 'twin-room-focus' ? 'rm1' : null,
    kind:'porch_post', id:'post:front-porch:0'});
  nodes.clear();
  globalThis.location = {pathname: shot.startsWith('twin') ? '/house/' + (['twin-editor','twin-awning-editor','twin-awning-box-editor','twin-posts','twin-downspout-hand','twin-room-focus','twin-post-card'].includes(shot)?'editor':'twin')
     : shot==='library-models'?'/house/library':shot==='wall-board'?'/home':'/app'};
  for(const selector of ['.pwa-brief-greet','.pwa-brief-day [data-kind]',
     '#plan-head .pwa-plan-title','.pwa-tl .pwa-ev','[x-data="homeBoard()"]',
     '#piece-card','canvas']) nodes.set(selector,node);
  const postsButton = {...node, textContent:'Move posts to the roof'};
  if(shot==='twin-posts')nodes.set('#piece-card button',postsButton);
  const leaveRoomButton = {...node, textContent:'Leave room'};
  if(shot==='twin-room-focus')nodes.set('#piece-card button',leaveRoomButton);
  const placedNote = {...node, textContent:'Placed by hand'};
  if(shot==='twin-downspout-hand') {
    nodes.set('#piece-card .editor-downspout-note', placedNote);
    nodes.set('.editor-handle-downspout', node);
  }
  const modelTab = '[data-library-tab="models"][aria-selected="true"]';
  const preview = 'canvas[aria-label="Orbit model preview with 6 ft scale figure"]';
  const properties = {...node, overflowY:'auto', getBoundingClientRect:()=>({top:80,bottom:850,left:950,right:1550})};
  const seat = {...node, textContent:'Seat Demo teak Real size', parentElement:properties,
    getBoundingClientRect:()=>({top:130,bottom:280,left:1000,right:1500})};
  if(shot==='library-models') {
    nodes.set(modelTab,node);
    nodes.set(preview,node);
    nodes.set('[data-model-part="Seat"]',seat);
    nodes.set('[data-model-parts] h3',node);
    for(const [i,key] of ['Frame','Cushion','Glass'].entries()) nodes.set(`[data-model-part="${key}"]`,{
      ...node, parentElement:properties,
      getBoundingClientRect:()=>({top:290+i*160,bottom:440+i*160,left:1000,right:1500}),
    });
    nodes.set('[data-model-progress]',{...node,textContent:''});
    nodes.set('[data-model-level="1"]',{...node,disabled:false});
    nodes.set('[data-model-level="2"]',{...node,disabled:false});
  }
  if(shot==='twin-post-card') {
    nodes.set('#piece-card h3',{...node,textContent:'Post 1'});
    nodes.set('[data-scene-id="post:front-porch:1"]',node);
  }
  if(shot==='board') {
    const sheet = {...node, hidden:false, getAttribute:a=>a==='data-active-index'?'0':null};
    const screen = {...node, hidden:false};
    const heroImg = {...node, complete:true, naturalWidth:480};
    nodes.set('[data-board-sheet]', sheet);
    nodes.set('[data-board-screen="0"]', screen);
    nodes.set('[data-board-screen="0"] .chf-board-hero img', heroImg);
  }
  assert.equal(check({shot,final:true}).ready, true, shot);
  if(shot==='library-models') {
    for(const selector of [modelTab, preview, '[data-model-part="Seat"]', '[data-model-progress]']) {
      const value=nodes.get(selector);
      nodes.delete(selector);
      assert.equal(check({shot,final:true}).ready,false,selector+' is required');
      nodes.set(selector,{...value,getClientRects:()=>[]});
      if(selector!=='[data-model-progress]') assert.equal(check({shot,final:true}).ready,false,selector+' must be visible');
      nodes.set(selector,value);
    }
    nodes.set('[data-model-progress]',{...node,textContent:'Preparing lighter versions…'});
    assert.equal(check({shot,final:true}).ready,false,'wait for lighter versions to finish');
    nodes.set('[data-model-progress]',{...node,textContent:''});
    nodes.set('[data-model-part="Seat"]',{...node,textContent:'Seat from the original'});
    assert.equal(check({shot,final:true}).ready,false,'Seat must show the actual Demo teak name');
    nodes.set('[data-model-part="Seat"]',seat);
    nodes.set('[data-model-part="Seat"]',{...seat,
      getBoundingClientRect:()=>({top:950,bottom:1100,left:1000,right:1500})});
    assert.equal(check({shot,final:true}).ready,false,'Seat below the fold is not ready');
    nodes.set('[data-model-part="Seat"]',{...seat,
      getBoundingClientRect:()=>({top:800,bottom:880,left:1000,right:1500})});
    assert.equal(check({shot,final:true}).ready,false,'Seat must fit fully inside its scroll container');
    nodes.set('[data-model-part="Seat"]',{...seat,
      getBoundingClientRect:()=>({top:-10,bottom:140,left:1000,right:1500})});
    assert.equal(check({shot,final:true}).ready,false,'Seat above viewport is not ready');
    nodes.set('[data-model-part="Seat"]',seat);
    for(const selector of ['[data-model-parts] h3','[data-model-part="Glass"]']) {
      const value=nodes.get(selector);
      nodes.set(selector,{...value,getBoundingClientRect:()=>({top:850,bottom:1000,left:1000,right:1500})});
      assert.equal(check({shot,final:true}).ready,false,'all four rows and Parts heading must be framed');
      nodes.set(selector,value);
    }
    for(const level of [1,2]) {
      const selector=`[data-model-level="${level}"]`;
      nodes.set(selector,{...node,disabled:true});
      assert.equal(check({shot,final:true}).ready,false,'initial empty progress is not finished levels');
      nodes.set(selector,{...node,disabled:false});
    }
  }
  if(shot==='twin-post-card') {
    for(const selection of [{kind:'porch',id:'post:front-porch:0'},
        {kind:'porch_post',id:'post:front-porch:1'},null]) {
      window.__twinEditor.selection=()=>selection;
      assert.equal(check({shot,final:true}).ready,false,'must select the first porch post');
    }
    window.__twinEditor.selection=()=>({kind:'porch_post',id:'post:front-porch:0'});
    nodes.set('#piece-card h3',{...node,textContent:'Post 2'});
    assert.equal(check({shot,final:true}).ready,false,'card must name Post 1');
    nodes.set('#piece-card h3',{...node,textContent:'Post 1'});
    nodes.delete('[data-scene-id="post:front-porch:1"]');
    assert.equal(check({shot,final:true}).ready,false,'sibling Post 2 row must exist');
    nodes.set('[data-scene-id="post:front-porch:1"]',{getClientRects:()=>[]});
    assert.equal(check({shot,final:true}).ready,false,'sibling Post 2 row must be visible');
    nodes.set('[data-scene-id="post:front-porch:1"]',node);
    nodes.delete('#piece-card');
    assert.equal(check({shot,final:true}).ready,false,'selected post must have a visible card');
    nodes.set('#piece-card',node);
  }
  if(shot==='board') {
    const sheet = nodes.get('[data-board-sheet]');
    const screen = nodes.get('[data-board-screen="0"]');
    const heroImg = nodes.get('[data-board-screen="0"] .chf-board-hero img');
    nodes.set('[data-board-sheet]', {...sheet, hidden:true});
    assert.equal(check({shot,final:true}).ready,false,'hidden board sheet is not ready');
    nodes.set('[data-board-sheet]', {...sheet, getAttribute:()=>'1'});
    assert.equal(check({shot,final:true}).ready,false,'look 1 must be the active screen');
    nodes.set('[data-board-sheet]', sheet);
    nodes.set('[data-board-screen="0"]', {...screen, hidden:true});
    assert.equal(check({shot,final:true}).ready,false,'look 1 screen must be visible');
    nodes.set('[data-board-screen="0"]', screen);
    nodes.set('[data-board-screen="0"] .chf-board-hero img', {...heroImg, complete:false});
    assert.equal(check({shot,final:true}).ready,false,'hero image must finish loading');
    nodes.set('[data-board-screen="0"] .chf-board-hero img', {...heroImg, naturalWidth:0});
    assert.equal(check({shot,final:true}).ready,false,'hero image must have naturalWidth > 0');
    nodes.set('[data-board-screen="0"] .chf-board-hero img', heroImg);
    nodes.set('[data-board-screen="0"] [data-board-img-placeholder]', node);
    assert.equal(check({shot,final:true}).ready,false,'broken image placeholder is not ready');
    nodes.delete('[data-board-screen="0"] [data-board-img-placeholder]');
  }
  if(shot==='twin-posts') {
    nodes.delete('#piece-card button');
    assert.equal(check({shot,final:true}).ready,false,'posts shot requires the actual action');
    nodes.set('#piece-card button',postsButton);
  }
  if(shot==='twin-room-focus') {
    window.__twinEditor.selection = () => ({room:null});
    assert.equal(check({shot,final:true}).ready,false,'room-focus shot requires focused room');
    window.__twinEditor.selection = () => ({room:'srm1'});
    assert.equal(check({shot,final:true}).ready,false,'room-focus shot requires Living room id rm1');
    window.__twinEditor.selection = () => ({room:'rm1'});
    nodes.delete('#piece-card button');
    assert.equal(check({shot,final:true}).ready,false,'room-focus shot requires visible Leave room button');
    nodes.set('#piece-card button',{...node, textContent:'Focus room'});
    assert.equal(check({shot,final:true}).ready,false,'room-focus shot requires Leave room label');
    nodes.set('#piece-card button',leaveRoomButton);
  }
  if(shot==='twin-awning-garden') {
    window.__twin.state.time = 'night';
    assert.equal(check({shot,final:true}).ready,false,'awning-garden shot requires daylight');
    window.__twin.state.time = 'auto';
    window.__twin.plan.buildings[0].roofs = [];
    assert.equal(check({shot,final:true}).ready,false,'awning-garden shot requires demo-awning');
    window.__twin.plan.buildings[0].roofs = [{id:'demo-awning'}];
  }
  if(shot==='twin-downspout-hand') {
    nodes.delete('#piece-card .editor-downspout-note');
    assert.equal(check({shot,final:true}).ready,false,'downspout-hand shot requires Placed by hand note');
    nodes.set('#piece-card .editor-downspout-note', placedNote);
    nodes.delete('.editor-handle-downspout');
    assert.equal(check({shot,final:true}).ready,false,'downspout-hand shot requires visible downspout handle');
    nodes.set('.editor-handle-downspout', node);
  }
  if(shot==='twin-eave-streams') {
    window.__twin.eaves.data.pours = [{}];
    assert.equal(check({shot,final:true}).ready,false,'eave-streams shot requires gutters off (no pours)');
    window.__twin.eaves.data.pours = [];
    window.__twin.weather.rate = 0;
    assert.equal(check({shot,final:true}).ready,false,'eave-streams shot requires heavy rain');
    window.__twin.weather.rate = 1;
  }
  if(shot==='twin-lit-models') {
    window.__twin.bake.fresh = () => [];
    assert.equal(check({shot,final:true}).ready,false,'lit-models shot requires fresh baked lamp');
    window.__twin.bake.fresh = () => ['light.demo_floor_lamp'];
    window.__twin.bake.models.stats = () => ({bricks:0});
    assert.equal(check({shot,final:true}).ready,false,'lit-models shot requires lit model bricks');
    window.__twin.bake.models.stats = () => ({bricks:4});
    window.__twin.state.time = 'day';
    assert.equal(check({shot,final:true}).ready,false,'lit-models shot requires night clock');
    window.__twin.state.time = 'night';
    window.__twin.levels.snapshot = () => ({level:'house'});
    assert.equal(check({shot,final:true}).ready,false,'lit-models shot requires floor view');
    window.__twin.levels.snapshot = () => ({level:'floor'});
  }
  for (const blocker of ['#panel-enrol', '#screen-login', '#pin-modal', '[x-data="adminGate()"] .fixed.inset-0']) {
    nodes.set(blocker,node);
    assert.equal(check({shot,final:true}).blocked, true, shot+' '+blocker);
    nodes.delete(blocker);
  }
  nodes.set('#panel-enrol',{getClientRects:()=>[]});
  assert.equal(check({shot,final:true}).blocked,false,shot+' hidden overlay');
  location.pathname='/account/login';
  assert.equal(check({shot,final:true}).ready,false,shot+' wrong route');
}
console.log('all sixteen surfaces reject visible pairing/sign-in overlays and wrong routes');
'''
        code, output = run_node(driver, {'root': ROOT.as_posix(), 'guard': SURFACE_STATE, 'shots': NAMES})
        self.assertEqual(code, 0, output)

    def test_library_parts_frame_scrolls_actual_container(self):
        sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
        from tools.demo_capture import LIBRARY_PARTS_FRAME, SURFACE_STATE
        from twin_editor_dom import PRELUDE, run_node
        driver = PRELUDE + r'''
const frame = new Function('return ('+input.frame+')')();
const check = new Function('return ('+input.guard+')')();
window.innerWidth=1600; window.innerHeight=900;
globalThis.location={pathname:'/house/library'};
const root={scrollTop:0,parentElement:null}; document.scrollingElement=root;
const right={parentElement:root,overflowY:'visible',scrollTop:0,scrollHeight:2200,clientHeight:760,
  getBoundingClientRect:()=>({top:100,bottom:860,left:950,right:1550})};
const node={getClientRects:()=>[{}]};
const contentNode=(top,height)=>({...node,parentElement:right,
  getBoundingClientRect:()=>({top:top-root.scrollTop-right.scrollTop,
    bottom:top+height-root.scrollTop-right.scrollTop,left:1000,right:1500})});
const heading=contentNode(1000,24);
const parts={parentElement:right,querySelector:s=>s==='h3'?heading:null};
const nodes=new Map([
  ['[data-model-parts]',parts],['[data-model-parts] h3',heading],
  ['[data-library-tab="models"][aria-selected="true"]',node],
  ['canvas[aria-label="Orbit model preview with 6 ft scale figure"]',node],
  ['[data-model-progress]',{...node,textContent:''}],
  ['[data-model-level="1"]',{...node,disabled:false}],
  ['[data-model-level="2"]',{...node,disabled:false}],
]);
for(const [i,key] of ['Seat','Frame','Cushion','Glass'].entries()) nodes.set(`[data-model-part="${key}"]`,{
  ...contentNode(1040+i*160,140),textContent:key==='Seat'?'Seat Demo teak':'original',
});
document.querySelector=s=>nodes.get(s)||null; document.querySelectorAll=()=>[];
document.getElementById=id=>id==='top-nav-bar'?{getBoundingClientRect:()=>({bottom:64})}:null;
globalThis.getComputedStyle=e=>({visibility:'visible',display:'block',overflowY:e.overflowY||'visible'});
const spec={shot:'library-models',final:true};
assert.equal(check(spec).ready,false,'parts initially below fold');
frame();
assert.equal(root.scrollTop,920,'current Library CSS scrolls the document, not the unbounded aside');
assert.equal(right.scrollTop,0);
assert.equal(check(spec).ready,true,'heading and all rows must fit after scrolling');
root.scrollTop=0; right.overflowY='auto';
assert.equal(check(spec).ready,false,'nested-container case starts clipped');
frame();
assert.equal(root.scrollTop,0,'nested scrollbar must not scroll the document');
assert.equal(right.scrollTop,884);
assert.equal(check(spec).ready,true,'rows must also fit a real containing scroll panel');
console.log('actual Parts framing script scrolls the document or nearest scroll panel');
'''
        code, output = run_node(driver, dict(root=ROOT.as_posix(), frame=LIBRARY_PARTS_FRAME, guard=SURFACE_STATE))
        self.assertEqual(code, 0, output)

    def test_readiness_timeout_names_shot(self):
        sys.path.insert(0, str(ROOT))
        from tools.demo_capture import _wait_surface
        from playwright.sync_api import TimeoutError as BrowserTimeout
        from unittest.mock import Mock
        page = Mock()
        page.wait_for_function.side_effect = BrowserTimeout('timeout')
        with self.assertRaisesRegex(RuntimeError, r'wall-board: board never became ready \(12000 ms\)'):
            _wait_surface(page, 'wall-board')
        with self.assertRaisesRegex(RuntimeError, r'library-models: model library never became ready \(60000 ms\)'):
            _wait_surface(page, 'library-models')
        self.assertEqual(page.wait_for_function.call_args.kwargs['timeout'], 60000)
        page.wait_for_function.side_effect = None
        page.evaluate.return_value = {'blocked': True, 'ready': True}
        with self.assertRaisesRegex(RuntimeError, 'twin-overview: sign-in or pairing screen'):
            _wait_surface(page, 'twin-overview')

    def test_settle_executes_and_bounds_promises(self):
        sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
        from tools.demo_capture import _settle, _ready_evaluate
        from twin_editor_dom import PRELUDE, run_node
        def record(dynamic_weather):
            scripts = []
            class Recorder:
                def evaluate(self, source, arg=None):
                    scripts.append([source, arg])
                def wait_for_function(self, source):
                    scripts.append([source, None])
            _settle(Recorder(), twin=True, dynamic_weather=dynamic_weather)
            return scripts
        strict_scripts = record(False)
        tolerant_scripts = record(True)
        bounded = []
        class BoundRecorder:
            def evaluate(self, source, arg=None):
                bounded.append(source)
        _ready_evaluate(BoundRecorder(), 'new Promise(() => {})')
        driver = PRELUDE + r'''
document.fonts = {ready:Promise.resolve()};
let compileCalls = 0, frameTick = 0, rafAlive = true;
const makeTwin = (callsFn, trisFn) => ({
  ready:true, stats:()=>({triangles:100}), scene:{}, camera:{},
  renderer3:{
    info:{programs:[1, 2], get render(){ return {calls: callsFn(frameTick), triangles: trisFn(frameTick)}; }},
    compileAsync:async()=>{ compileCalls++; },
  },
});
globalThis.requestAnimationFrame = callback => { if (rafAlive) setTimeout(() => { if (rafAlive) { frameTick++; callback(); } }, 1); };

async function runScripts(scripts, timeoutOverride = null) {
  for (const [source, arg] of scripts) {
    const value = new Function('return (' + source + ')')();
    if (typeof value === 'function') await value(timeoutOverride ?? arg);
    else assert.equal(value, true);
  }
}

// 1. Strict path settles with exact counts and runs compileAsync.
window.__twin = makeTwin(() => 100, () => 10000);
await runScripts(input.strict);
assert.equal(compileCalls, 1, 'strict _settle must run compileAsync');

// 2. Dynamic-weather path settles under <=2% jitter on calls/triangles and runs compileAsync.
window.__twin = makeTwin(t => (t % 2 ? 100 : 101), t => (t % 2 ? 10000 : 10150));
await runScripts(input.tolerant);
assert.equal(compileCalls, 2, 'dynamic_weather _settle must still run compileAsync');

// 3. Dynamic-weather path rejects >2% draw/triangle swings (must not settle).
window.__twin = makeTwin(t => (t % 2 ? 100 : 110), () => 10000);
await assert.rejects(runScripts([input.tolerant[2]], 80), /readiness exceeded 80 ms/);

// 4. Strict path still rejects small 1% jitter (exact signature preserved for existing shots).
window.__twin = makeTwin(t => (t % 2 ? 100 : 101), () => 10000);
await assert.rejects(runScripts([input.strict[2]], 80), /readiness exceeded 80 ms/);

await assert.rejects(new Function('return (' + input.bounded + ')')()(20), /readiness exceeded 20 ms/);
rafAlive = false;
console.log('actual font/scene/shader readiness scripts settle, enforce 2% tolerance, and run compileAsync');
'''
        code, output = run_node(driver, dict(root=ROOT.as_posix(), strict=strict_scripts,
                                             tolerant=tolerant_scripts, bounded=bounded[0]))
        self.assertEqual(code, 0, output)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT.parent,
                              text=True, capture_output=True, timeout=35)

    def test_list(self):
        sys.path.insert(0, str(ROOT))
        from tools import demo_capture as demo
        self.assertEqual(list(demo.SURFACE_LABELS), NAMES)
        self.assertEqual(demo.SURFACE_LABELS['library-models'], 'model library')
        self.assertEqual(demo.SURFACE_LABELS['twin-post-card'], 'patio post card')
        self.assertEqual(demo.SURFACE_LABELS['board'], 'presentation board')
        expected = [*demo.SHOTS, *(f'{name} (opt-in)' for name in demo.OPT_IN_SHOTS)]
        result = self.cli('--list')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), expected)
        self.assertEqual(result.stderr, '')

    def test_opt_in_shots_excluded_from_default(self):
        sys.path.insert(0, str(ROOT))
        from tools import demo_capture as demo
        opt_in = ('twin-eave-streams', 'twin-lit-models', 'twin-awning-garden', 'twin-downspout-hand', 'twin-room-focus', 'library-models', 'twin-post-card', 'board')
        for name in opt_in:
            self.assertNotIn(name, demo.SHOTS)
            self.assertIn(name, demo.OPT_IN_SHOTS)
        with tempfile.TemporaryDirectory() as out, patch.object(demo, 'capture') as cap:
            self.assertEqual(demo.main(['--out', out]), 0)
            self.assertEqual(cap.call_args.args[1], list(demo.SHOTS))
            for name in opt_in:
                cap.reset_mock()
                self.assertEqual(demo.main(['--out', out, '--shot', name]), 0)
                self.assertEqual(cap.call_args.args[1], [name])

    def test_list_ignores_timeout(self):
        sys.path.insert(0, str(ROOT))
        from tools import demo_capture as demo
        expected = [*demo.SHOTS, *(f'{name} (opt-in)' for name in demo.OPT_IN_SHOTS)]
        for value in ('10', 'abc'):
            with self.subTest(value=value):
                result = self.cli('--list', '--timeout', value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)
                self.assertEqual(result.stderr, '')

    def test_invalid_timeout(self):
        for value in ('10', '601', 'abc', '170.5'):
            with self.subTest(value=value):
                result = self.cli('--out', 'unused', '--timeout', value)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')
                self.assertEqual(len(result.stderr.splitlines()), 1)
                self.assertTrue(result.stderr.startswith('demo_capture: '), result.stderr)
                self.assertIn('--timeout', result.stderr)

    def test_timeout_reaches_worker_deadline(self):
        sys.path.insert(0, str(ROOT))
        from tools import demo_capture as demo
        for arguments, seconds in (([], 82), (['--timeout', '170'], 170),
                                   (['--timeout', '30'], 30), (['--timeout', '600'], 600)):
            with self.subTest(seconds=seconds), tempfile.TemporaryDirectory() as out:
                process = Mock()
                process.communicate.side_effect = subprocess.TimeoutExpired('worker', seconds)
                process.poll.return_value = None
                errors = io.StringIO()
                with patch.object(demo.subprocess, 'Popen', return_value=process), \
                     patch.object(demo, 'process_tree', return_value=nullcontext(None)), \
                     patch.object(demo, '_resume_worker'), \
                     patch.object(demo.os, 'killpg', create=True), redirect_stderr(errors):
                    result = demo.main(['--out', out, '--shot', 'my-day', *arguments])
                process.communicate.assert_called_once_with(b'1', timeout=seconds)
                process.wait.assert_called_once_with(timeout=5)
                self.assertEqual(result, 1)
                self.assertEqual(errors.getvalue(), f'demo_capture: capture exceeded {seconds} seconds\n')

    def test_unknown_shot(self):
        with tempfile.TemporaryDirectory() as out:
            result = self.cli('--out', out, '--shot', 'not-a-shot')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(result.stderr.startswith('demo_capture: '), result.stderr)

    def test_argument_error(self):
        result = self.cli()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(result.stderr.splitlines()), 1)
        self.assertTrue(result.stderr.startswith('demo_capture: '))

    def test_worker_failure_cleans_data_and_children(self):
        sys.path.insert(0, str(ROOT))
        from tools import demo_capture as demo
        original = subprocess.Popen
        # A launch failure can leave a browser grandchild alive. Hold a file
        # open in that grandchild: Windows cannot delete it until the job stops.
        script = r'''
import json, os, pathlib, subprocess, sys, time
sys.stdin.read(1)
data = pathlib.Path(os.environ['CHAUFFEUR_DATA_DIR'])
child = subprocess.Popen([sys.executable, '-c',
    "import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); f=(p/'held').open('w'); (p/'ready').touch(); time.sleep(60)",
    str(data)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
deadline = time.monotonic() + 5
while not (data / 'ready').exists() and time.monotonic() < deadline:
    time.sleep(.02)
assert (data / 'ready').exists()
pathlib.Path(sys.argv[1], 'record.json').write_text(json.dumps({'data': str(data), 'child': child.pid}))
(data / 'capture-error.txt').write_text('simulated launch failure')
sys.exit(1)
'''
        with tempfile.TemporaryDirectory() as out:
            def fake_worker(command, **kwargs):
                return original([sys.executable, '-c', script, out], **kwargs)
            with patch.object(demo.subprocess, 'Popen', fake_worker):
                with self.assertRaisesRegex(RuntimeError, 'simulated launch failure'):
                    demo.capture(out, ['my-day'])
            record = json.loads((Path(out) / 'record.json').read_text())
            self.assertFalse(Path(record['data']).exists())
            if os.name == 'nt':
                import ctypes
                from ctypes import wintypes as W
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [W.DWORD, W.BOOL, W.DWORD], W.HANDLE
                kernel.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
                kernel.CloseHandle.argtypes = [W.HANDLE]
                handle = kernel.OpenProcess(0x1000, False, record['child'])
                if handle:
                    try:
                        status = W.DWORD()
                        self.assertTrue(kernel.GetExitCodeProcess(handle, ctypes.byref(status)))
                        self.assertNotEqual(status.value, 259, 'grandchild still running')
                    finally:
                        kernel.CloseHandle(handle)

    def test_isolation_and_seed(self):
        # Poison a VALID database in the inherited folder. The child audits all
        # opens as well as proving this member never made it into the new DB.
        with tempfile.TemporaryDirectory() as sentinel:
            poison = Path(sentinel) / 'db.json'
            poison.write_text(json.dumps({'members': {'1': {
                'id': 'sentinel', 'name': 'SENTINEL_DO_NOT_LOAD', 'role': 'parent'}}}), encoding='utf-8')
            before = poison.read_bytes()
            code = r'''
import json, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path.cwd()))
from tools.demo_capture import isolated_data
sentinel = pathlib.Path(os.environ['CHAUFFEUR_DATA_DIR']).resolve()
def audit(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        target = pathlib.Path(os.fsdecode(args[0])).resolve()
        assert target != sentinel and sentinel not in target.parents, 'opened sentinel'
sys.addaudithook(audit)
with isolated_data() as data:
    assert pathlib.Path(data).resolve() != sentinel
    assert pathlib.Path(data).name.startswith('chauffeur_demo_')
    assert not list(pathlib.Path(data).iterdir())
    assert 'HA_BASE_URL' not in os.environ
    from tools.demo_seed import seed, household, synthetic_plan
    seed()
    from services import storage, twin_store
    assert pathlib.Path(storage.DB_PATH).parent == pathlib.Path(data)
    assert 'SENTINEL_DO_NOT_LOAD' not in json.dumps(storage.get_all_members())
    assert [m['name'] for m in storage.get_all_members()] == ['Avery', 'Jordan', 'Pip', 'Milo']
    model = twin_store.current_model()
    assert sum(bool(e.get('gutter')) for b in model['buildings'] for r in b.get('roofs', []) for e in r['edges']) >= 2
    assert len(storage.get_routines()) == 2
    assert len(household()['schedule']['events']) >= 14
    storage.db.close()
assert not pathlib.Path(data).exists(), 'temporary data was not cleaned up'
print('isolated seed passed')
'''
            env = dict(os.environ, CHAUFFEUR_DATA_DIR=sentinel, HA_BASE_URL='sentinel.invalid')
            result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=35)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(list(Path(sentinel).iterdir()), [poison])
            self.assertEqual(poison.read_bytes(), before)

    def test_no_fixture_identity_or_sensitive_devices(self):
        sys.path.insert(0, str(ROOT))
        from tools.demo_seed import household, demo_plan, INVENTED_TEXT, visible_strings
        data = dict(household(), plan=demo_plan())
        text = json.dumps(data).casefold()
        visible = visible_strings(data)
        self.assertTrue(INVENTED_TEXT)
        self.assertTrue(visible)
        self.assertTrue(visible <= INVENTED_TEXT, 'seed contains text outside the invented vocabulary')
        self.assertEqual([m['name'] for m in data['members']], ['Avery', 'Jordan', 'Pip', 'Milo'])
        for device in data['devices']:
            for entity, _state, _attrs in device['entities']:
                self.assertIn(entity.split('.')[0], ('light', 'sensor'))
        self.assertNotIn('@', text)

    def test_household_guard_prevents_still(self):
        # Actual seed and screenshot entry point, without a browser. Corrupt
        # each invariant independently and prove screenshot is never called.
        code = r'''
import os, pathlib, sys
from unittest.mock import Mock, patch
from tools import demo_capture as demo
from tools.demo_seed import seed
with demo.isolated_data() as directory:
    data,_=seed()
    data['data_dir']=directory
    from services import storage
    page=Mock()
    page.evaluate.return_value=True
    out=pathlib.Path(directory)
    with patch.object(demo,'_settle'), patch.object(demo,'_assert_surface'):
        demo._save_still(page,'my-day',out,data)
        page.screenshot.assert_called_once()
        page.reset_mock()
        cases=[patch.object(storage,'DB_PATH',str(out.parent/'decoy-db.json')),
               patch.object(storage.db,'path',str(out.parent/'decoy.sqlite3')),
               patch.object(storage,'get_all_members',return_value=storage.get_all_members()[:-1]),
               patch.object(storage,'get_all_members',return_value=storage.get_all_members()+[{'id':'decoy'}])]
        for shot in ('twin-overview', 'twin-eave-streams', 'twin-lit-models', 'twin-awning-garden', 'twin-downspout-hand', 'twin-room-focus'):
            for case in cases:
                with case:
                    try: demo._save_still(page,shot,out,data,True)
                    except RuntimeError as error: assert shot+':' in str(error)
                    else: raise AssertionError('invalid household admitted for ' + shot)
                page.screenshot.assert_not_called()
        page.evaluate.return_value=False
        for shot in ('my-day','plan','wall-board'):
            try: demo._save_still(page,shot,out,data)
            except RuntimeError as error: assert shot+':' in str(error)
            else: raise AssertionError('missing demo content admitted')
            page.screenshot.assert_not_called()
print('per-still household/content guard passed')
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                text=True, capture_output=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_demo_content_predicate(self):
        sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
        from tools.demo_capture import DEMO_CONTENT
        from twin_editor_dom import PRELUDE, run_node
        driver = PRELUDE + r'''
const check = new Function('return ('+input.predicate+')')();
const node={innerText:'Moonkite team practice',getClientRects:()=>[{}]};
document.querySelectorAll=()=>[node];
globalThis.getComputedStyle=()=>({visibility:'visible',display:'block'});
for(const shot of ['my-day','plan','wall-board']) {
  const spec={shot,markers:['Moonkite team practice']};
  node.innerText='Moonkite team practice';
  assert.equal(check(spec),true,shot);
  node.innerText='PLANTED_OTHER_HOUSEHOLD';
  assert.equal(check(spec),false,shot);
  node.innerText='Moonkite team practice'; node.getClientRects=()=>[];
  assert.equal(check(spec),false,shot+' hidden'); node.getClientRects=()=>[{}];
}
'''
        code, output = run_node(driver, dict(root=ROOT.as_posix(), predicate=DEMO_CONTENT))
        self.assertEqual(code, 0, output)

    def test_browser_clock_uses_household_date_and_zone(self):
        sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from tools import demo_capture as demo
        from tools.demo_seed import household, demo_morning, DEMO_TIMEZONE
        import live_app
        morning = demo_morning(datetime.fromisoformat('2024-01-15T02:30:00+00:00'))
        data = dict(household(morning.date()), capture_time=morning.isoformat(),
                    panel_token='PLANTED_DEMO_TOKEN', _isolation=Mock())
        page = Mock()
        page.locator.return_value.is_visible.return_value = False
        served = Mock(port=12345)
        served.browser.return_value = nullcontext(page)
        with patch.object(live_app, 'goto_retry'), patch.object(demo, '_wait_surface'), \
             patch.object(demo, '_save_still'):
            demo._capture_pages(served, data, 'PLANTED_DEMO_TOKEN', Path('unused'), ['plan'])
        self.assertEqual(served.browser.call_args.kwargs['timezone_id'], DEMO_TIMEZONE)
        clock = page.clock.set_fixed_time.call_args.args[0]
        self.assertEqual(clock.isoformat(), morning.isoformat())
        self.assertEqual(clock.astimezone(ZoneInfo(DEMO_TIMEZONE)).date().isoformat(), '2024-01-14')
        page.context.route.assert_called_once()
        page.context.route_web_socket.assert_called_once()

    def test_exit_two_preserves_output(self):
        with tempfile.TemporaryDirectory() as out:
            for name in NAMES:
                (Path(out) / (name + '.png')).write_bytes(b'preexisting')
            for arguments in (['--shot','unknown'], ['--timeout','abc']):
                result = self.cli('--out',out,*arguments)
                self.assertEqual(result.returncode,2)
                self.assertTrue(all((Path(out)/(name+'.png')).read_bytes()==b'preexisting' for name in NAMES))

    def test_library_capture_uses_isolated_context_and_non_twin_settle(self):
        sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
        from tools import demo_capture as demo, demo_seed
        import live_app
        now = demo_seed.demo_morning()
        data = dict(demo_seed.household(now.date()), capture_time=now.isoformat(),
                    panel_token='PLANTED_DEMO_TOKEN', _isolation=Mock())
        desktop, page, context = Mock(), Mock(), Mock()
        page.locator.return_value.is_visible.return_value = False
        context.new_page.return_value = page
        desktop.context.browser.new_context.return_value = nullcontext(context)
        served = Mock(port=12345)
        served.browser.return_value = nullcontext(desktop)
        with patch.object(demo_seed, 'seed_library_model', return_value='import-demo') as seed, \
             patch.object(live_app, 'goto_retry') as navigate, \
             patch.object(demo, '_wait_surface'), patch.object(demo, '_assert_surface'), \
             patch.object(demo, '_save_still') as save:
            demo._capture_pages(served, data, 'PLANTED_DEMO_TOKEN', Path('unused'), ['library-models'])
        seed.assert_called_once_with()
        self.assertEqual(desktop.context.browser.new_context.call_args.kwargs['viewport'],
                         dict(width=1600, height=900))
        served.url.assert_called_with('house/library?model=import-demo')
        self.assertIs(navigate.call_args.args[0], page)
        self.assertEqual(page.wait_for_function.call_args.kwargs['arg'], dict(shot='library-models', final=True))
        self.assertGreaterEqual(page.wait_for_function.call_args.kwargs['timeout'], 60000)
        self.assertIn(((demo.LIBRARY_PARTS_FRAME,), {}), page.evaluate.call_args_list)
        save.assert_called_once_with(page, 'library-models', Path('unused'), data, False, before_shot=None)
        page.context.route.assert_called_once()
        page.context.route_web_socket.assert_called_once()

    def test_served_seed_without_browser(self):
        # Exercise the actual worker startup and HTTP routes; replace only the
        # browser capture so the no-browser suite also catches swallowed errors.
        code = r'''
import json, os, pathlib, sys
sys.path.insert(0, str(pathlib.Path.cwd()))
from tools import demo_capture as demo
from tools import demo_seed
from datetime import datetime
evening = datetime.fromisoformat('2024-01-15T02:30:00+00:00')
morning = demo_seed.demo_morning(evening)
demo_seed.demo_morning = lambda instant=None: morning
from urllib.request import Request, urlopen
root = pathlib.Path.cwd()
forbidden = [(root / 'data').resolve(), (root.parent / 'data').resolve()]
def audit(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        target = pathlib.Path(os.fsdecode(args[0])).resolve()
        assert not any(target == folder or folder in target.parents for folder in forbidden), 'opened repository data'
sys.addaudithook(audit)
import requests
outbound = []
def no_outbound(self, method, url, *args, **kwargs):
    outbound.append(url)
    raise AssertionError('demo attempted an external HTTP request')
requests.Session.request = no_outbound
def probe(served, data, token, out, shots):
    from services import storage, twin_store
    from services import arrive_by
    from datetime import datetime, date
    assert datetime.now().date().isoformat() == '2024-01-14'
    assert date.today().isoformat() == '2024-01-14'
    assert arrive_by._dt(evening) is evening, 'original datetime lost its identity under the frozen clock'
    assert data['capture_time'] == '2024-01-14T08:12:00-05:00'
    assert data['schedule']['events'][0]['start'].startswith('2024-01-14')
    assert storage.get_settings()['timezone'] == 'America/New_York'
    assert data['_isolation'].active, 'served app must use the live isolation guard'
    demo._assert_household('wall-board', data)
    panel = storage.get_device_by_token(data['panel_token'])
    assert panel and panel['kind'] == 'panel' and panel['label'] == 'Moonkite demo panel'
    def get(path):
        with urlopen(Request(served.url(path), headers={'X-Member-Token': token}), timeout=15) as response:
            return response.read()
    for path in ['app', 'home?panel=true&kiosk=true', 'house/twin?test=1', 'house/editor?test=1']:
        assert b'<html' in get(path), path
    schedule = json.loads(get('api/schedule'))
    assert len(schedule['events']) == 21, schedule
    assert len(schedule['drivers']) == 2, schedule
    board = json.loads(get('api/home_board'))
    types = {tile['type'] for tile in board['tiles']}
    assert {'drives', 'chores', 'lists'} <= types, types
    assert board['hero'], board
    # Exercise wall APIs with the DEVICE credential alone, as nav.html does.
    for path in ['api/panel/profile', 'api/home_board', 'api/house/twin']:
        with urlopen(Request(served.url(path), headers={'X-Device-Token': data['panel_token'],
                'X-Device-Id': 'demo-panel'}), timeout=15) as response:
            payload = json.load(response)
            assert response.status == 200
    from tools.demo_seed import GUTTER_OUTLET_CAMERA
    from twin_editor_dom import PRELUDE, run_node
    kit = json.loads((root / 'twin_kits/modern_farmhouse.json').read_text())
    kit['manifest'] = {}
    driver = PRELUDE + r"""
const THREE = await import('three');
const {buildTwin} = await import(file('static/twin/twin_generator.js'));
const G = await import(file('static/twin/gutters.js'));
const twin = buildTwin(input.plan,input.kit,'high');
const placement = G.cachedGutterPlacement(input.plan);
assert.ok(placement.runs.length && placement.spouts.length);
let gutterFaces=0;
twin.root.traverse(o=>{gutterFaces+=(o.userData?.snapRanges||[]).filter(r=>r.surfaceKind==='gutter').length;});
assert.ok(gutterFaces>0,'actual rendered gutter/downspout geometry');
const before=G._gutterPlacementStats.calls;
let framed;
window.__twin = {plan:input.plan, eaves:{data:{instances:[]}},
  levels:{go(){}}, controls:{}, setCameraState:value=>framed=value};
window.chfBase = '';
globalThis.location = {href:file('index.html')};
await new Function('return ('+input.camera+')')()(true);
assert.ok(framed, 'dry camera must frame a static downspout');
assert.equal(G._gutterPlacementStats.calls,before,'camera must reuse the renderer placement cache');
const spout=placement.spouts.find(s=>s.id===window.__demoGutterFrame.spout);
assert.ok(spout && spout.mount==='wall' && spout.run.startsWith('synth-house:'));
const camera=new THREE.PerspectiveCamera(38,1600/900,.1,1000);
camera.position.set(...framed.position); camera.lookAt(new THREE.Vector3(...framed.target)); camera.updateMatrixWorld(true);
for (const point of [spout.top,spout.outlet.at]) {
  const p=new THREE.Vector3(...point).project(camera);
  assert.ok(Math.abs(p.x)<.95 && Math.abs(p.y)<.95 && p.z<1,'gutter outlet and full downspout must fit');
}
console.log('served dry twin geometry and cached camera passed');

// Project actual rendered building bounds, including porch, overhangs, gables
// and the separate hip wing. Yard/lot geometry must not dilute this assertion.
const bounds = new THREE.Box3();
twin.root.updateMatrixWorld(true);
for (const group of [...Object.values(twin.groups.levels), twin.groups.roof, twin.groups.gableFull])
  bounds.union(new THREE.Box3().setFromObject(group));
const corners = [bounds.min.x,bounds.max.x].flatMap(x => [bounds.min.y,bounds.max.y].flatMap(y =>
  [bounds.min.z,bounds.max.z].map(z => new THREE.Vector3(x,y,z))));
const overview = new THREE.PerspectiveCamera(38,1600/900,.1,1000);
  // Use exactly the pose passed by the capture command. Leave 15% clear on
  // every side of the usable frame above the 76px panel shelf at 1600x900.
  overview.position.fromArray(input.overview.position);
  overview.lookAt(new THREE.Vector3(...input.overview.target)); overview.updateMatrixWorld(true);
  const width=1600, height=900, navTop=height-76, margin=.15;
  const pixels = corners.map(point => {
    const p=point.clone().project(overview), x=(p.x+1)*width/2, y=(1-p.y)*height/2;
    assert.ok(p.z>-1 && p.z<1, 'overview corner must be in front of the camera');
    assert.ok(x>=width*margin && x<=width*(1-margin), 'complete gables/wing with horizontal margin');
    assert.ok(y>=navTop*margin && y<=navTop*(1-margin), 'complete roof/porch above the shelf with ground margin');
    return [x,y];
  });
  console.log('overview projected pixel bounds',JSON.stringify({
    x:[Math.min(...pixels.map(p=>p[0])),Math.max(...pixels.map(p=>p[0]))],
    y:[Math.min(...pixels.map(p=>p[1])),Math.max(...pixels.map(p=>p[1]))]}));
"""
    code, output = run_node(driver, dict(root=root.as_posix(), plan=payload['plan'], kit=kit,
                                        camera=GUTTER_OUTLET_CAMERA, overview=demo.OVERVIEW_CAMERA), timeout=60)
    assert code == 0, output
    assert not outbound, 'demo must not attempt geocoding or other external HTTP'
    print('seeded HTTP surfaces passed')
demo._capture_pages = probe
try:
    demo._worker(os.environ['CHAUFFEUR_DATA_DIR'], list(demo.SHOTS))
except SystemExit:
    error = pathlib.Path(os.environ['CHAUFFEUR_DATA_DIR']) / 'capture-error.txt'
    print(error.read_text() if error.exists() else 'worker failed', file=sys.stderr)
    raise
'''
        with tempfile.TemporaryDirectory(prefix='chauffeur_demo_http_') as data:
            from tools.demo_isolation import worker_environment
            env = worker_environment(data, dict(os.environ, HA_TOKEN='PLANTED_DECOY',
                                                SUPERVISOR_TOKEN='PLANTED_DECOY', MAPBOX_API_KEY='PLANTED_DECOY'))
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code], cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


    def test_sofa_glb_bytes_unchanged(self):
        import hashlib
        sys.path.insert(0, str(ROOT))
        from tools.demo_seed import demo_sofa_glb
        # Captured from the unmodified seed before adding optional UV buffers.
        payload = demo_sofa_glb()
        self.assertEqual(len(payload), 124888)
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         '3b9d5fab14ba54b256602eb861ac8bbdf82b9c7fee88605697de512c8d4fb262')

    def test_library_model_seed_and_browser_parts_stamp(self):
        code = r'''
import base64, json, os, pathlib, struct, sys, tempfile
from unittest.mock import patch
sys.path[:0] = [str(pathlib.Path.cwd()), str(pathlib.Path.cwd() / 'tests')]
from tools.demo_capture import isolated_data
from tools.demo_seed import seed_library_model, INVENTED_TEXT

# Refuse missing/non-demo paths before importing services or writing anything.
os.environ.pop('CHAUFFEUR_DATA_DIR', None)
try:
    seed_library_model()
except RuntimeError:
    pass
else:
    raise AssertionError('missing demo path accepted')
with tempfile.TemporaryDirectory(prefix='normal_data_') as real_dir:
    os.environ['CHAUFFEUR_DATA_DIR'] = real_dir
    try:
        seed_library_model()
    except RuntimeError:
        pass
    else:
        raise AssertionError('non-demo path accepted')
    assert not list(pathlib.Path(real_dir).iterdir())
    assert 'services.storage' not in sys.modules

with isolated_data() as data:
    from services import storage, twin_imports, twin_library, twin_materials, twin_model_records, twin_store
    # Even a valid demo folder must refuse service paths pointing elsewhere.
    with patch.object(storage, 'DB_PATH', str(pathlib.Path(data).parent / 'db.json')):
        try:
            seed_library_model()
        except RuntimeError as exc:
            assert 'storage' in str(exc)
        else:
            raise AssertionError('non-demo storage accepted')
    with patch.object(twin_store, 'DATA_DIR', str(pathlib.Path(data).parent)):
        try:
            seed_library_model()
        except RuntimeError as exc:
            assert 'twin store' in str(exc)
        else:
            raise AssertionError('non-demo twin store accepted')
    with patch.object(twin_imports, 'create', wraps=twin_imports.create) as create, \
         patch.object(twin_model_records, 'update', wraps=twin_model_records.update) as update, \
         patch.object(twin_materials, 'create', wraps=twin_materials.create) as create_material, \
         patch.object(twin_library, '_urlopen', side_effect=AssertionError('demo material must not download')):
        asset_id = seed_library_model()
    files, label, kind = create.call_args.args
    assert list(files) == ['demo_garden_bench.glb']
    assert label == 'Demo garden bench' and label in INVENTED_TEXT and kind == 'furniture'
    record = twin_model_records.get(asset_id)
    parts = record['parts']
    assert [p['key'] for p in parts] == ['Seat', 'Frame', 'Cushion', 'Glass']
    assert [p['name'] for p in parts] == [p['key'] for p in parts]
    assert [p['has_uv'] for p in parts] == [True, False, True, True]
    assert [p['opaque'] for p in parts] == [True, True, True, False]
    assert record['parts_version'] == 1 and record['revision'] == 3
    create_material.assert_called_once_with({'name': 'Demo teak', 'params': {'tint': '#9a5b2e', 'roughness': 0.6}}, 'avery')
    teak_id = record['materials']['Seat']['material']
    teak = twin_materials.get(teak_id)
    assert teak['name'] == 'Demo teak' and teak['name'] in INVENTED_TEXT
    assert teak['source'] == 'user' and teak['maps'] == {} and teak['created_by'] == 'avery'
    assert teak['params']['tint'] == '#9a5b2e' and teak['params']['roughness'] == 0.6
    assert record['materials'] == {'Seat': {'material': teak_id, 'texture': 'real'}}
    assert update.call_count == 2
    assert update.call_args_list[0].args == (asset_id, {'parts': parts, 'parts_version': 1}, 1)
    assert update.call_args_list[1].args == (asset_id, {'materials': record['materials']}, 2)
    assert twin_imports.get(asset_id)['name'] == label
    payload = files['demo_garden_bench.glb']
    doc = json.loads(payload[20:20 + struct.unpack_from('<I', payload, 12)[0]])
    primitives = doc['meshes'][0]['primitives']
    assert len(primitives) == 4
    assert [m['name'] for m in doc['materials']] == [p['key'] for p in parts]
    assert doc['materials'][0]['pbrMetallicRoughness']['baseColorFactor'] == [0.78, 0.78, 0.76, 1.0]
    assert doc['materials'][3]['alphaMode'] == 'BLEND'
    assert doc['materials'][3]['pbrMetallicRoughness']['baseColorFactor'][3] == 0.35
    bin_start = 28 + struct.unpack_from('<I', payload, 12)[0]
    for primitive, part in zip(primitives, parts):
        attrs = primitive['attributes']
        assert ('TEXCOORD_0' in attrs) == part['has_uv']
        assert doc['accessors'][primitive['indices']]['count'] // 3 == part['triangles'] > 0
        if part['has_uv']:
            uv = doc['accessors'][attrs['TEXCOORD_0']]
            assert uv['type'] == 'VEC2' and uv['count'] == doc['accessors'][attrs['POSITION']]['count']
            offset = bin_start + doc['bufferViews'][uv['bufferView']]['byteOffset']
            values = struct.unpack_from('<' + str(uv['count'] * 2) + 'f', payload, offset)
            assert min(values) == 0 and max(values) == 1
            # Each beveled-box face owns a 6x6 vertex grid spanning the UV square.
            for start in range(0, len(values), 72):
                face = values[start:start + 72]
                assert min(face[::2]) == min(face[1::2]) == 0
                assert max(face[::2]) == max(face[1::2]) == 1
    positions = [doc['accessors'][p['attributes']['POSITION']] for p in primitives]
    width = max(p['max'][0] for p in positions) - min(p['min'][0] for p in positions)
    height = max(p['max'][1] for p in positions) - min(p['min'][1] for p in positions)
    assert 1.4 < width < 1.7 and .85 < height < 1

# Decode the actual GLB in the browser's loader and execute its real stampParts.
from twin_editor_dom import PRELUDE, run_node
driver = PRELUDE + r"""
const {GLTFLoader} = await import('three/addons/loaders/GLTFLoader.js');
const {stampParts} = await import(file('static/twin/model_levels.js'));
const bytes = Uint8Array.from(Buffer.from(input.glb,'base64'));
const parsed = await new GLTFLoader().parseAsync(bytes.buffer,'');
assert.deepEqual(stampParts(parsed.scene), input.parts);
console.log('actual browser loader and stampParts agree with the seeded record');
"""
status, output = run_node(driver, {'root':pathlib.Path.cwd().as_posix(),
                                 'glb':base64.b64encode(payload).decode(), 'parts':parts})
assert status == 0, output
print('library import, revisions, defaults, guards, GLB geometry and browser parts stamp passed')
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_post_selection_uses_scene_disclosures(self):
        sys.path.insert(0, str(ROOT))
        from tools.demo_capture import _select_demo_post, _show_demo_post_rows
        events = []
        expanded = set()
        selected = []

        class Row:
            def __init__(self, key):
                self.key = key

            def locator(self, selector):
                if selector == '..':
                    return self
                if selector.startswith('[data-row-disclosure]'):
                    return Disclosure(self.key)
                self.assert_select(selector)
                return self

            def assert_select(self, selector):
                self_outer.assertEqual(selector, '[data-scene-select]')

            def count(self):
                if 'post:front-porch:' in self.key:
                    return int(len(expanded) == 3)
                return 1

            def scroll_into_view_if_needed(self):
                events.append(('scroll', self.key))

            def click(self):
                selected.append(self.key)

        class Disclosure(Row):
            def count(self):
                return int(self.key not in expanded)

            def click(self):
                expanded.add(self.key)
                events.append(('expand', self.key))

        self_outer = self
        page = Mock()
        host = Mock()
        page.locator.side_effect = lambda selector: host if selector == '#scene-tree' else Mock()
        host.locator.side_effect = Row
        _select_demo_post(page)
        self.assertEqual(selected, ['[data-scene-id="post:front-porch:0"]'])
        self.assertEqual([key for action, key in events if action == 'expand'], [
            '[data-scene-id="synth-house"]', '[data-floor="synth-house:L1"]', '[data-scene-id="front-porch"]'])
        self.assertIn(('scroll', '[data-scene-id="post:front-porch:1"]'), events)
        # A repeated shot leaves already-open ancestors alone.
        _select_demo_post(page)
        self.assertEqual(sum(action == 'expand' for action, key in events), 3)
        page.wait_for_selector.assert_called_with('#piece-card', state='visible')

        # Execute Claude's real post-selection scroll and readiness scripts,
        # with the browser-reported regression coordinates. Removing the scroll
        # leaves the first row above pane.top and makes this readiness fail.
        actions = []
        framed_page = Mock()
        framed_page.evaluate.side_effect = lambda script: actions.append(('evaluate', script))
        framed_page.wait_for_function.side_effect = lambda script, **kw: actions.append(('wait', script))
        _show_demo_post_rows(framed_page)
        from twin_editor_dom import PRELUDE, run_node
        driver = PRELUDE + r'''
let top=123, scrolled=false;
document.getElementById=id=>({getBoundingClientRect:()=>({top:160,bottom:490})});
document.querySelector=selector=>({
  getBoundingClientRect:()=>selector.includes(':0')?{top,bottom:top+36}:{top:top+36,bottom:top+72},
  scrollIntoView:options=>{
    assert.ok(selector.includes('post:front-porch:1'));
    assert.equal(options.block,'center'); top=270; scrolled=true;
  },
});
for(const [kind,script] of input.actions) {
  const fn=new Function('return ('+script+')')();
  if(kind==='wait') {
    assert.equal(scrolled,true,'the row must be centered before checking readiness');
    assert.equal(fn(),true,'both rows must now be fully inside Scene');
  } else fn();
}
assert.equal(scrolled,true);
console.log('post rows above Scene are centered before readiness');
'''
        code, output = run_node(driver, dict(root=ROOT.as_posix(), actions=actions))
        self.assertEqual(code, 0, output)

    def test_demo_furniture_glbs_and_furnish_refuses_real_data(self):
        code = r'''
import os, pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path.cwd()))
from tools import demo_capture as demo
from tools.demo_seed import demo_furniture_glbs, demo_plan, furnish_demo_room, seed, INVENTED_TEXT, DEMO_LAMP_ENTITY

# 1. Procedural GLBs use only invented vocabulary and have valid GLB headers.
glbs = demo_furniture_glbs()
assert set(glbs) == {'sofa', 'coffee_table', 'armchair', 'floor_lamp'}, glbs.keys()
for key, (label, filename, payload) in glbs.items():
    assert label in INVENTED_TEXT, label
    assert filename.endswith('.glb') and payload[:4] == b'glTF'

# 2. Gutters-off plan variant leaves gutters on in default demo_plan().
default_plan = demo_plan()
off_plan = demo_plan(gutters_on=False)
assert sum(bool(e.get('gutter')) for b in default_plan['buildings'] for r in b.get('roofs', []) for e in r['edges']) >= 6
assert sum(bool(e.get('gutter')) for b in off_plan['buildings'] for r in b.get('roofs', []) for e in r['edges']) == 0
assert not any(s.get('gutters') for b in off_plan['buildings'] for s in b['roof']['sections'])
assert not any(p.get('gutter') for b in off_plan['buildings'] for p in b.get('porches', []))

# 3. furnish_demo_room refuses a real/non-demo folder BEFORE importing services, with no writes.
with tempfile.TemporaryDirectory(prefix='normal_data_') as real_dir:
    os.environ['CHAUFFEUR_DATA_DIR'] = real_dir
    try:
        furnish_demo_room()
    except RuntimeError as exc:
        assert 'demo' in str(exc).lower()
    else:
        raise AssertionError('furnish_demo_room admitted a non-demo directory')
    assert list(pathlib.Path(real_dir).iterdir()) == []
    assert 'services.storage' not in sys.modules, 'furnish imported storage before refusing non-demo dir'

# 4. furnish_demo_room succeeds inside isolated_data() and places all 4 items + lamp fixture.
with demo.isolated_data() as data:
    seed()
    from services import twin_imports, twin_store
    for key, (_label, filename, payload) in glbs.items():
        tris = twin_imports._inspect(filename, {filename: payload})
        assert tris >= 100, (key, tris)
    assets = furnish_demo_room()
    assert len(assets) == 4
    model = twin_store.current_model()
    main = next(b for b in model['buildings'] if b['id'] == 'synth-house')
    ids = {item['id'] for item in main.get('items', [])}
    assert {'demo-sofa', 'demo-coffee-table', 'demo-armchair', 'demo-floor-lamp'} <= ids, ids
    assert DEMO_LAMP_ENTITY in (model.get('light_fixtures') or {}), model.get('light_fixtures')
    assert len(model['light_fixtures'][DEMO_LAMP_ENTITY]) == 1
print('furniture GLBs, gutters-off variant and furnish isolation passed')
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_board_capture_uses_phone_context(self):
        sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
        from tools import demo_capture as demo, demo_seed
        import live_app
        now = demo_seed.demo_morning()
        data = dict(demo_seed.household(now.date()), capture_time=now.isoformat(),
                    panel_token='PLANTED_DEMO_TOKEN', _isolation=Mock())
        desktop, page, context = Mock(), Mock(), Mock()
        page.locator.return_value.is_visible.return_value = False
        context.new_page.return_value = page
        desktop.context.browser.new_context.return_value = nullcontext(context)
        served = Mock(port=12345)
        served.browser.return_value = nullcontext(desktop)
        with patch.object(demo_seed, 'seed_board', return_value={'project_id': 'aa11', 'board_id': 'bb22'}) as seed, \
             patch.object(live_app, 'goto_retry') as navigate, \
             patch.object(demo, '_wait_surface'), patch.object(demo, '_assert_surface'), \
             patch.object(demo, '_save_still') as save:
            demo._capture_pages(served, data, 'PLANTED_DEMO_TOKEN', Path('unused'), ['board'])
        seed.assert_called_once_with()
        kwargs = desktop.context.browser.new_context.call_args.kwargs
        self.assertEqual(kwargs['viewport'], dict(width=390, height=844))
        self.assertEqual(kwargs['device_scale_factor'], 2)
        self.assertTrue(kwargs['is_mobile'])
        served.url.assert_called_with('app#board-aa11-bb22')
        self.assertIs(navigate.call_args.args[0], page)
        save.assert_called_once_with(page, 'board', Path('unused'), data, False, before_shot=None)

    def test_board_seed_guards_and_contents(self):
        code = r'''
import io, os, pathlib, re, sys, tempfile
from unittest.mock import patch
from PIL import Image
sys.path[:0] = [str(pathlib.Path.cwd()), str(pathlib.Path.cwd() / 'tests')]
from tools.demo_capture import isolated_data
from tools.demo_isolation import assert_household
from tools.demo_seed import seed, seed_board, INVENTED_TEXT

os.environ.pop('CHAUFFEUR_DATA_DIR', None)
try:
    seed_board()
except RuntimeError:
    pass
else:
    raise AssertionError('missing demo path accepted')
with tempfile.TemporaryDirectory(prefix='normal_data_') as real_dir:
    os.environ['CHAUFFEUR_DATA_DIR'] = real_dir
    try:
        seed_board()
    except RuntimeError:
        pass
    else:
        raise AssertionError('non-demo path accepted')
    assert not list(pathlib.Path(real_dir).iterdir())
    assert 'services.storage' not in sys.modules

with isolated_data() as data:
    seed()
    from services import boards, boards_contract as C, page_lookup, storage
    with patch.object(storage, 'DB_PATH', str(pathlib.Path(data).parent / 'db.json')):
        try:
            seed_board()
        except RuntimeError as exc:
            assert 'storage' in str(exc)
        else:
            raise AssertionError('non-demo storage accepted')
    ids = seed_board()
    assert set(ids) == {'project_id', 'board_id'}, ids
    project = storage.get_project(ids['project_id'])
    assert project and project['title'] == 'Demo concert outfit' and project['audience'] == 'household'
    board = boards.get(ids['board_id'])
    assert board and board['layout'] == 'options' and board['noun'] == 'looks'
    assert len(board['slots']) == 4 and len(board['options']) == 3
    lookups = storage.lookups_table.all()
    assert len(lookups) == 12, len(lookups)
    assert all(re.fullmatch(r'lk_[0-9a-f]{10}', r['id']) for r in lookups)
    assert all(r['url'].startswith('https://demo.invalid/') for r in lookups)
    assert all(r['store'] in INVENTED_TEXT and r['title'] in INVENTED_TEXT for r in lookups)
    img_dir = pathlib.Path(boards.image_dir(board['id']))
    for lid in boards.lookup_ids(board):
        p = img_dir / f'{lid}.jpg'
        assert p.is_file(), p
        with Image.open(p) as im:
            assert im.format == 'JPEG' and im.size == (480, 480)
    with patch.object(page_lookup, 'fetch', side_effect=AssertionError('must serve from cache')):
        for lid in boards.lookup_ids(board):
            assert len(boards.image_bytes(board, lid)) > 1000
    view = boards.view(board, storage.get_member('avery'))
    assert set(view) == C.VIEW_KEYS and view['summary_line'] == f'3 looks{C.SEPARATOR}from $148'
    dm = storage.get_or_create_dm(storage.ARGYLE_MEMBER_ID, 'avery')
    msgs = storage.get_channel_messages(dm['id'], limit=10)
    assert len(msgs) == 2 and msgs[0]['card'] is None and msgs[1]['card']['kind'] == 'board'
    assert msgs[1]['card']['board_id'] == board['id']
    assert_household(storage, data)
print('board seed guards, lookups, cached tiles, view and Argyle DM passed')
'''
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
