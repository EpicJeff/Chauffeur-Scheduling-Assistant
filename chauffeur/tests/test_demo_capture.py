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
         'twin-eave-streams', 'twin-lit-models', 'twin-awning-garden', 'twin-downspout-hand']


class DemoCaptureTests(unittest.TestCase):
    def test_surface_guards_reject_overlays(self):
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT / 'tests'))
        from tools.demo_capture import SURFACE_STATE
        from twin_editor_dom import PRELUDE, run_node
        driver = PRELUDE + r'''
const check = new Function('return (' + input.guard + ')')();
const node = {getClientRects: () => [{}]};
const nodes = new Map();
document.querySelector = selector => nodes.get(selector) || null;
document.querySelectorAll = selectors => selectors.split(',').map(s=>nodes.get(s.trim())).filter(Boolean);
globalThis.getComputedStyle = () => ({visibility:'visible', display:'block'});
window.Alpine = {$data: () => ({board:{tiles:[{}]}})};
window.__editor = {ready:true, selected:()=>({pieceId:'r1',buildingId:'synth-house'})};
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
  window.__editor.selected = () => ({pieceId:shot.startsWith('twin-awning-')?'demo-awning':shot==='twin-posts'?'front-porch':'r1',buildingId:'synth-house'});
  nodes.clear();
  globalThis.location = {pathname: shot.startsWith('twin') ? '/house/' + (['twin-editor','twin-awning-editor','twin-awning-box-editor','twin-posts','twin-downspout-hand'].includes(shot)?'editor':'twin')
     : shot==='wall-board'?'/home':'/app'};
  for(const selector of ['.pwa-brief-greet','.pwa-brief-day [data-kind]',
     '#plan-head .pwa-plan-title','.pwa-tl .pwa-ev','[x-data="homeBoard()"]',
     '#piece-card','canvas']) nodes.set(selector,node);
  const postsButton = {...node, textContent:'Move posts to the roof'};
  if(shot==='twin-posts')nodes.set('#piece-card button',postsButton);
  const placedNote = {...node, textContent:'Placed by hand'};
  if(shot==='twin-downspout-hand') {
    nodes.set('#piece-card .editor-downspout-note', placedNote);
    nodes.set('.editor-handle-downspout', node);
  }
  assert.equal(check({shot,final:true}).ready, true, shot);
  if(shot==='twin-posts') {
    nodes.delete('#piece-card button');
    assert.equal(check({shot,final:true}).ready,false,'posts shot requires the actual action');
    nodes.set('#piece-card button',postsButton);
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
console.log('all thirteen surfaces reject visible pairing/sign-in overlays and wrong routes');
'''
        code, output = run_node(driver, {'root': ROOT.as_posix(), 'guard': SURFACE_STATE, 'shots': NAMES})
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
        expected = [*demo.SHOTS, *(f'{name} (opt-in)' for name in demo.OPT_IN_SHOTS)]
        result = self.cli('--list')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), expected)
        self.assertEqual(result.stderr, '')

    def test_opt_in_shots_excluded_from_default(self):
        sys.path.insert(0, str(ROOT))
        from tools import demo_capture as demo
        opt_in = ('twin-eave-streams', 'twin-lit-models', 'twin-awning-garden', 'twin-downspout-hand')
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
        for shot in ('twin-overview', 'twin-eave-streams', 'twin-lit-models', 'twin-awning-garden', 'twin-downspout-hand'):
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


if __name__ == '__main__':
    unittest.main()
