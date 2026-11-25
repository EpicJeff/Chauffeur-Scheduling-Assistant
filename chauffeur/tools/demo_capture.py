r"""Capture invented Chauffeur release-card stills. Run from the repository root.

Hub command (180000 ms outer timeout):
    venv\Scripts\python.exe chauffeur/tools/demo_capture.py --timeout 170 --out "<dir>"

Opt-in shots (pass --shot <name>; twin-lit-models needs --timeout 240):
    venv\Scripts\python.exe chauffeur/tools/demo_capture.py --shot twin-eave-streams --timeout 170 --out "<dir>"
    venv\Scripts\python.exe chauffeur/tools/demo_capture.py --shot twin-lit-models --timeout 240 --out "<dir>"

All service imports live in the isolated worker. The supervisor owns its data
directory and process tree, including a browser that fails during launch.
Only requested shot filenames are replaced. Capture failures clear requested
stills and preserve unrequested stills. Exit-2 argument errors leave the output
folder untouched.
"""
import argparse
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ('my-day', 'plan', 'wall-board', 'twin-overview', 'twin-editor', 'twin-gutters', 'twin-awning-editor', 'twin-awning-box-editor', 'twin-posts')
# Adding twin-eave-streams pushes the full default run over 145 s, and
# twin-lit-models (lighting bake + model warmup) needs --timeout 240 on its own,
# so both new shots are opt-in by name (--shot <name>) rather than in SHOTS.
OPT_IN_SHOTS = ('twin-eave-streams', 'twin-lit-models')
ALL_SHOTS = SHOTS + OPT_IN_SHOTS
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
READY_TIMEOUT = 12000
TWIN_READY_TIMEOUT = 25000
BAKE_TIMEOUT = 90000
SURFACE_LABELS = dict(zip(ALL_SHOTS, ('brief', 'plan', 'board', 'twin', 'editor', 'gutters',
                                      'awning editor', 'awning ends and ceiling', 'patio posts',
                                      'eave streams', 'lit models')))
# Demo-only three-quarter hero pose, in scene metres. The viewer's default
# floor-outline fit excludes the porch/overhangs and the panel's bottom shelf.
# The served-model projection test reserves 15% around the complete buildings
# within the 1600x824 area above the 76px shelf.
OVERVIEW_CAMERA = dict(position=[-9, 12.5, 20], target=[8.3, 0.2, -2.1])
# Close elevated SE framing putting dark wet porch deck & lawn behind both the
# porch eave (c=1.0 heavy streams, left) and the hip wing eave (c<=0.35 thin
# streams, right) in one frame. Target extends 32 m along the look ray so the
# precipitation volume spreads naturally instead of crowding the camera lens.
EAVE_STREAMS_CAMERA = dict(position=[12.8, 4.3, 10.6], target=[3.05, -3.68, -18.88])
# Shader time (seconds) in a 3-second window where porch and main-eave sheet
# surges align with active full-drop streams beneath them (no mid-air cutoffs).
EAVE_STREAMS_TIME_S = 1057.0
# Angled cutaway into Demo cottage Living (L1) showing sofa, coffee table,
# armchair, glowing floor lamp, lit pool and baked shadows at night.
LIT_MODELS_CAMERA = dict(position=[6.9, 4.7, 0.5], target=[3.85, 0.50, -4.35])

# Evaluated both in Chromium and in the no-browser DOM regression. A ready
# scene alone says nothing about an authentication overlay covering its canvas.
SURFACE_STATE = r"""({shot, final = false}) => {
  const visible = el => !!el && el.getClientRects().length > 0
    && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
  const seen = selector => visible(document.querySelector(selector));
  const blocked = [...document.querySelectorAll(
    '#panel-enrol, #screen-login, #pin-modal, [x-data="adminGate()"] .fixed.inset-0')].some(visible);
  const path = location.pathname.replace(/\/$/, '');
  const view = window.__twin;
  const twin = !!(view?.ready && view.plan?.buildings?.some(b => b.id === 'synth-house')
    && view.stats().triangles > 0 && seen('canvas'));
  let ready = false;
  if (shot === 'my-day') ready = path.endsWith('/app') && seen('.pwa-brief-greet')
    && seen('.pwa-brief-day [data-kind]');
  if (shot === 'plan') ready = path.endsWith('/app') && seen('#plan-head .pwa-plan-title')
    && seen('.pwa-tl .pwa-ev');
  if (shot === 'wall-board') {
    const el = document.querySelector('[x-data="homeBoard()"]');
    ready = path.endsWith('/home') && visible(el) && (window.Alpine?.$data(el)?.board?.tiles || []).length > 0;
  }
  if (shot === 'twin-overview' || shot === 'twin-gutters') {
    ready = path.endsWith('/house/twin') && twin;
    if (shot === 'twin-gutters' && final) ready = ready && !!window.__demoGutterFrame?.spout;
  }
  if (shot === 'twin-eave-streams') {
    ready = path.endsWith('/house/twin') && twin;
    if (final) ready = ready && view.eaves?.group?.visible === true
      && (view.eaves?.data?.instances?.length || 0) > 0
      && (view.eaves?.data?.pours?.length || 0) === 0
      && view.weather?.precip === 'rain' && view.weather?.rate >= 0.99 && view.weather?.wetness >= 0.99;
  }
  if (shot === 'twin-lit-models') {
    ready = path.endsWith('/house/twin') && twin;
    if (final) ready = ready && (view.bake?.fresh?.() || []).includes('light.demo_floor_lamp')
      && (view.bake?.models?.stats?.()?.bricks || 0) >= 3
      && view.state?.time === 'night' && view.levels?.snapshot?.()?.level === 'floor';
  }
  if (shot === 'twin-editor' || shot === 'twin-awning-editor' || shot === 'twin-awning-box-editor' || shot === 'twin-posts') {
    ready = path.endsWith('/house/editor') && twin && window.__editor?.ready === true;
    if (final) ready = ready && seen('#piece-card')
      && window.__editor.selected()?.pieceId === (shot.startsWith('twin-awning-') ? 'demo-awning' : shot === 'twin-posts' ? 'front-porch' : 'r1');
    if (shot === 'twin-posts' && final) ready = ready && [...document.querySelectorAll('#piece-card button')]
      .some(button => visible(button) && button.textContent === 'Move posts to the roof');
  }
  return {blocked, ready: !!ready};
}"""


@contextmanager
def _shot_stage(name, stage, timeout=READY_TIMEOUT):
    from playwright.sync_api import TimeoutError as BrowserTimeout
    try:
        yield
    except BrowserTimeout:
        raise RuntimeError(f'{name}: {stage} never became ready ({timeout} ms)') from None
    except Exception as error:
        reason = ' '.join(str(error).split())
        if reason.startswith(name + ':'):
            raise
        raise RuntimeError(f'{name}: {reason}') from None


def _assert_surface(page, name, final=False):
    state = page.evaluate(SURFACE_STATE, dict(shot=name, final=final))
    if state['blocked']:
        raise RuntimeError(f'{name}: sign-in or pairing screen is visible')
    if not state['ready']:
        raise RuntimeError(f'{name}: expected {SURFACE_LABELS[name]} is not visible')


def _wait_surface(page, name):
    timeout = TWIN_READY_TIMEOUT if name.startswith('twin-') else READY_TIMEOUT
    with _shot_stage(name, SURFACE_LABELS[name], timeout=timeout):
        page.wait_for_function(
            '(spec) => { const s = (' + SURFACE_STATE + ')(spec); return s.blocked || s.ready; }',
            arg=dict(shot=name), timeout=timeout)
        # Preserve the brief's existing optional PIN-setup dismissal. It may
        # arrive after DOMContentLoaded, while the authenticated data loads.
        if page.locator('#pin-modal-skip').is_visible():
            page.locator('#pin-modal-skip').click()
            page.wait_for_function(
                '(spec) => { const s = (' + SURFACE_STATE + ')(spec); return s.blocked || s.ready; }',
                arg=dict(shot=name), timeout=timeout)
        _assert_surface(page, name)


@contextmanager
def isolated_data():
    """Override inherited paths BEFORE any service import; never inspect them."""
    data = tempfile.mkdtemp(prefix='chauffeur_demo_')
    keys = ('CHAUFFEUR_DATA_DIR', 'HA_BASE_URL', 'CHAUFFEUR_MEDIA_ROOT')
    previous = {key: os.environ.get(key) for key in keys}
    os.environ['CHAUFFEUR_DATA_DIR'] = data
    os.environ.pop('HA_BASE_URL', None)
    os.environ.pop('CHAUFFEUR_MEDIA_ROOT', None)
    try:
        yield data
    finally:
        # The worker has exited and all descendants have been stopped first.
        try:
            storage = sys.modules.get('services.storage')
            if storage is not None and Path(storage.DB_PATH).parent == Path(data):
                try:
                    storage.db.close()
                except OSError:
                    pass
            _remove_temp(data)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def _remove_temp(directory):
    # Job termination releases handles asynchronously. Retry every OSError;
    # delayed cleanup must not change the result of a completed capture.
    for attempt in range(16):
        try:
            shutil.rmtree(directory)
            return
        except FileNotFoundError:
            return
        except OSError:
            if attempt < 15:
                time.sleep(.1)


@contextmanager
def process_tree():
    """Windows job lifetime contains even orphaned Chromium subprocesses."""
    if os.name != 'nt':
        yield None
        return
    import ctypes
    from ctypes import wintypes as W

    class Limits(ctypes.Structure):
        _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                    ('flags', W.DWORD), ('min_working', ctypes.c_size_t),
                    ('max_working', ctypes.c_size_t), ('active', W.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

    class Extended(ctypes.Structure):
        _fields_ = [('basic', Limits), ('io', IO), ('process_memory', ctypes.c_size_t),
                    ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                    ('peak_job', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [W.LPVOID, W.LPCWSTR], W.HANDLE
    kernel.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, W.LPVOID, W.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        def assign(process):
            if not kernel.AssignProcessToJobObject(job, W.HANDLE(int(process._handle))):
                raise ctypes.WinError(ctypes.get_last_error())
        yield assign
    finally:
        kernel.CloseHandle(job)


def capture(out, shots, timeout=82):
    from tools.demo_isolation import worker_environment
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    _clear_shots(out, shots)
    try:
        _capture_staged(out, shots, timeout, worker_environment)
    except BaseException:
        _clear_shots(out, shots)
        raise


def _clear_shots(out, shots):
    for name in shots:
        (out / (name + '.png')).unlink(missing_ok=True)


def _publish_stills(stage, out, shots):
    """Cross-drive copy, then same-directory rename; never expose half a PNG."""
    pending = []
    try:
        for name in shots:
            descriptor, filename = tempfile.mkstemp(prefix='.chauffeur-demo-', suffix='.tmp', dir=out)
            pending.append((Path(filename), out / (name + '.png')))
            os.close(descriptor)
            shutil.copyfile(stage / (name + '.png'), filename)
        for temporary, destination in pending:
            os.replace(temporary, destination)
    finally:
        for temporary, _destination in pending:
            temporary.unlink(missing_ok=True)


def _resume_worker(process):
    if os.name == 'nt':
        # Popen closes the primary thread handle. NtResumeProcess resumes that
        # suspended process only after AssignProcessToJobObject has succeeded.
        import ctypes
        from ctypes import wintypes as W
        resume = ctypes.WinDLL('ntdll').NtResumeProcess
        resume.argtypes, resume.restype = [W.HANDLE], W.LONG
        if resume(W.HANDLE(int(process._handle))) < 0:
            raise RuntimeError('could not resume isolated demo worker')


def _capture_staged(out, shots, timeout, worker_environment):
    with isolated_data() as data:
        stage = Path(tempfile.mkdtemp(prefix='chauffeur_demo_stills_'))
        command = (f'import sys; sys.path.insert(0, {str(ROOT)!r}); '
                   'from tools.demo_capture import _worker; '
                   'sys.stdin.read(1); _worker(sys.argv[1], sys.argv[2:])')
        process = None
        try:
            with process_tree() as assign:
                try:
                    process = subprocess.Popen([sys.executable, '-I', '-B', '-c', command, str(stage), *shots],
                        cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, start_new_session=os.name != 'nt',
                        env=worker_environment(data), creationflags=0x4 if os.name == 'nt' else 0)
                    if assign:
                        assign(process)
                    _resume_worker(process)
                    # The interpreter itself cannot run until job assignment.
                    process.communicate(b'1', timeout=timeout)
                    if process.returncode:
                        error = Path(data) / 'capture-error.txt'
                        reason = error.read_text(encoding='utf-8') if error.exists() else 'capture worker failed'
                        raise RuntimeError(reason)
                finally:
                    if process is not None:
                        if os.name != 'nt':
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        elif process.poll() is None:
                            process.kill()
            if any(not (stage / (name + '.png')).is_file() for name in shots):
                raise RuntimeError('capture worker did not produce every requested still')
            _publish_stills(stage, out, shots)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f'capture exceeded {timeout} seconds') from None
        finally:
            try:
                if process is not None:
                    process.wait(timeout=5)
            finally:
                _remove_temp(stage)


def _ready_evaluate(page, expression, timeout=READY_TIMEOUT):
    """Bound promise-based readiness too; Page.evaluate has no timeout option."""
    # Coerce the resolved value to null so Playwright never serializes huge
    # objects like THREE.Scene (which renderer.compileAsync resolves to) over CDP.
    page.evaluate('''(timeout) => {
      let timer;
      return Promise.race([Promise.resolve(''' + expression + ''').then(() => null), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('readiness exceeded ' + timeout + ' ms')), timeout);
      })]).finally(() => clearTimeout(timer));
    }''', timeout)


def _settle(page, twin=False, dynamic_weather=False):
    _ready_evaluate(page, 'document.fonts.ready')
    if twin:
        # ready is false during scene builds and async surface compiles. Then
        # require stable program/draw counts across frames, not an arbitrary nap.
        # Live rain splashes cause small per-frame draw/triangle jitter, so
        # dynamic_weather allows a 2% relative tolerance on those counts while
        # keeping exact matching for programs and for all other shots.
        page.wait_for_function('window.__twin?.ready === true && window.__twin.stats().triangles > 0')
        if dynamic_weather:
            _ready_evaluate(page, """new Promise(resolve => {
              let last = null, stable = 0, started = performance.now();
              const close = (a, b) => Math.abs(a - b) <= Math.max(Math.abs(a), Math.abs(b)) * 0.02;
              function frame() {
                const v = window.__twin;
                const progs = v.renderer3.info.programs.length;
                const calls = v.renderer3.info.render.calls;
                const tris = v.renderer3.info.render.triangles;
                const same = !!last && v.ready && progs === last.progs
                  && close(calls, last.calls) && close(tris, last.tris);
                if (same) stable += 1;
                else { stable = v.ready ? 1 : 0; last = v.ready ? {progs, calls, tris} : null; }
                if (stable >= 20 && performance.now() - started >= 1800) resolve();
                else requestAnimationFrame(frame);
              }
              requestAnimationFrame(frame);
            })""")
        else:
            _ready_evaluate(page, """new Promise(resolve => {
              let last = '', stable = 0, started = performance.now();
              function frame() {
                const v = window.__twin;
                const signature = [v.ready, v.renderer3.info.programs.length,
                  v.renderer3.info.render.calls, v.renderer3.info.render.triangles].join(':');
                stable = signature === last && v.ready ? stable + 1 : 0;
                last = signature;
                if (stable >= 20 && performance.now() - started >= 1800) resolve();
                else requestAnimationFrame(frame);
              }
              requestAnimationFrame(frame);
            })""")
        _ready_evaluate(page, 'window.__twin.renderer3.compileAsync(window.__twin.scene, window.__twin.camera)')
    page.wait_for_function("""() => ![...document.querySelectorAll(
      '[aria-busy="true"], [role="progressbar"], .animate-spin')].some(e => e.getClientRects().length)""")
    page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')


DEMO_CONTENT = r"""({shot, markers}) => {
  const selector = shot === 'my-day' ? '.pwa-brief-day'
    : shot === 'plan' ? '.pwa-tl .pwa-ev' : '[x-data="homeBoard()"]';
  return [...document.querySelectorAll(selector)].some(el => el.getClientRects().length > 0
    && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none'
    && markers.some(marker => (el.innerText || '').includes(marker)));
}"""


def _assert_household(name, data):
    from tools.demo_isolation import assert_household
    from services import storage
    guard = data.get('_isolation')
    root = guard.data if guard is not None else os.environ['CHAUFFEUR_DATA_DIR']
    try:
        assert_household(storage, root)
    except RuntimeError as error:
        raise RuntimeError(f'{name}: {error}') from None


def _save_still(page, name, out, data, twin=False, before_shot=None):
    with _shot_stage(name, 'scene' if twin else SURFACE_LABELS[name]):
        _settle(page, twin, dynamic_weather=(name == 'twin-eave-streams'))
        if before_shot is not None:
            before_shot()
        _assert_surface(page, name, final=True)
        _assert_household(name, data)
        if name in ('my-day', 'plan', 'wall-board'):
            markers = {event['title'] for event in data['schedule']['events']}
            if name == 'wall-board':
                markers.update(chore['title'] for chore in data['chores'])
                markers.add(data['shopping']['name'])
            if not page.evaluate(DEMO_CONTENT, dict(shot=name, markers=sorted(markers))):
                raise RuntimeError(f'{name}: no invented demo event or tile is visible')
        page.screenshot(path=str(out / (name + '.png')), full_page=False, animations='disabled')


def _restrict_browser(context, served, guard):
    from urllib.parse import urlparse
    def local(url, schemes):
        parsed = urlparse(url)
        return parsed.scheme in schemes and parsed.netloc == f'127.0.0.1:{served.port}'
    def request(route):
        guard.counts['browser.request'] += 1
        if local(route.request.url, ('http', 'https')):
            route.continue_()
        else:
            guard.blocked['browser.request'] += 1
            route.abort()
    def websocket(route):
        guard.counts['browser.websocket'] += 1
        if local(route.url, ('ws', 'wss')):
            route.connect_to_server()
        else:
            guard.blocked['browser.websocket'] += 1
            route.close()
    # Context routing also protects popups and child pages. Service workers
    # remain disabled by the existing context options.
    context.route('**/*', request)
    context.route_web_socket('**/*', websocket)


def _capture_pages(served, data, token, out, shots):
    from datetime import datetime, timezone
    import house_editor_model_harness as H
    from live_app import goto_retry
    from tools.demo_seed import GUTTER_OUTLET_CAMERA, DEMO_TIMEZONE

    # Seed, browser and server share this aware morning in the demo household's
    # zone, even when the UTC date has already rolled over in the US evening.
    now = datetime.fromisoformat(data['capture_time'])
    values = dict(chauffeur_member_id='avery', chauffeur_member_token=token,
                  chauffeur_member_token_for='avery', chauffeur_admin_token=token,
                  chauffeur_admin_token_for='avery', chauffeur_driver_id='d0',
                  chauffeur_theme='light', chauffeur_myday_day_open='1')
    values['chauffeur.twin.modes.v1'] = json.dumps(['lights', 'climate', 'energy'])
    def prepare(page, view='myday'):
        page.set_default_timeout(READY_TIMEOUT)
        page.set_default_navigation_timeout(READY_TIMEOUT)
        page.clock.set_fixed_time(now)
        settings = dict(values, chauffeur_view=view)
        page.add_init_script("""if (location.protocol.startsWith('http')) {
          const settings = """ + json.dumps(settings) + """;
          const panel = new URLSearchParams(location.search).get('panel') === 'true';
          if (panel) {
            for (const key of Object.keys(settings))
              if (/^chauffeur_(admin|member)_/.test(key)) localStorage.removeItem(key);
            localStorage.setItem('chauffeur_device_id', 'demo-panel');
            localStorage.setItem('chauffeur_device_token', """ + json.dumps(data['panel_token']) + """);
          } else {
            localStorage.removeItem('chauffeur_device_token');
            localStorage.removeItem('chauffeur_device_id');
          }
          for (const [key,value] of Object.entries(settings))
            if (!panel || !/^chauffeur_(admin|member)_/.test(key)) localStorage.setItem(key,value);
        }""")
        _restrict_browser(page.context, served, data['_isolation'])

    def save(page, name, twin=False, before_shot=None):
        _save_still(page, name, out, data, twin, before_shot=before_shot)

    def navigate(page, name, path):
        timeout = TWIN_READY_TIMEOUT if name.startswith('twin-') else READY_TIMEOUT
        with _shot_stage(name, SURFACE_LABELS[name], timeout=timeout):
            goto_retry(page, served.url(path), timeout=timeout)
            if page.locator('#pin-modal-skip').is_visible():
                page.locator('#pin-modal-skip').click()
            _wait_surface(page, name)

    with served.browser(launch_args=H.GPU_ARGS, device_scale_factor=1,
                        reduced_motion='reduce', timezone_id=DEMO_TIMEZONE, service_workers='block') as desktop:
        desktop.set_viewport_size(dict(width=1600, height=900))
        if 'my-day' in shots:
            with desktop.context.browser.new_context(viewport=dict(width=390, height=844),
                    device_scale_factor=2, is_mobile=True, has_touch=True,
                    reduced_motion='reduce', timezone_id=DEMO_TIMEZONE, service_workers='block') as phone:
                page = phone.new_page()
                prepare(page)
                navigate(page, 'my-day', 'app')
                save(page, 'my-day')
        prepare(desktop, 'family')
        if 'plan' in shots:
            navigate(desktop, 'plan', 'app')
            save(desktop, 'plan')
        if 'wall-board' in shots:
            navigate(desktop, 'wall-board', 'home?panel=true&kiosk=true')
            save(desktop, 'wall-board')
        if set(shots) & {'twin-overview', 'twin-gutters', 'twin-eave-streams'}:
            name = next(n for n in ('twin-overview', 'twin-gutters', 'twin-eave-streams') if n in shots)
            navigate(desktop, name, 'house/twin?tier=high&test=1&panel=true&kiosk=true')
            with _shot_stage(name, 'twin daylight'):
                desktop.evaluate('(iso) => window.__twin.setClock(iso)', now.replace(hour=12, tzinfo=timezone.utc).isoformat())
            if 'twin-overview' in shots:
                with _shot_stage('twin-overview', 'overview framing'):
                    desktop.evaluate('(pose) => window.__twin.setCameraState(pose)', OVERVIEW_CAMERA)
                save(desktop, 'twin-overview', True)
            if 'twin-gutters' in shots:
                with _shot_stage('twin-gutters', 'gutter framing'):
                    _assert_surface(desktop, 'twin-gutters')
                    desktop.evaluate(GUTTER_OUTLET_CAMERA, True)
                save(desktop, 'twin-gutters', True)
            if 'twin-eave-streams' in shots:
                with _shot_stage('twin-eave-streams', 'heavy rain and eave streams'):
                    desktop.evaluate("""async (pose) => {
                      const v = window.__twin;
                      const plan = structuredClone(v.plan);
                      for (const b of plan.buildings || []) {
                        for (const s of b.roof?.sections || []) delete s.gutters;
                        for (const r of b.roofs || []) for (const e of r.edges || []) delete e.gutter;
                        for (const p of b.porches || []) delete p.gutter;
                      }
                      await v.rebuild(plan);
                      v.levels.go({ level: 'house' }, { immediate: true });
                      v.setWeatherPreview('rain-stopping');
                      v.setCameraState(pose);
                      v.render();
                    }""", EAVE_STREAMS_CAMERA)
                    desktop.wait_for_function("""() => {
                      const v = window.__twin, w = v?.weather;
                      return w?.precip === 'rain' && w.rate >= 0.99 && w.wetness >= 0.99
                        && v.eaves?.group?.visible === true
                        && (v.eaves?.data?.instances?.length || 0) > 0
                        && (v.eaves?.data?.pours?.length || 0) === 0
                        && (v.eaves?.uniforms?.eaveFlow?.value || 0) >= 0.95;
                    }""", timeout=READY_TIMEOUT)
                def align_eave_phase():
                    desktop.evaluate("""async (targetS) => {
                      if (!window.__demoOrigPerfNow) window.__demoOrigPerfNow = performance.now.bind(performance);
                      const offset = targetS * 1000 - window.__demoOrigPerfNow();
                      performance.now = () => window.__demoOrigPerfNow() + offset;
                      window.__twin.render();
                      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
                    }""", EAVE_STREAMS_TIME_S)
                try:
                    save(desktop, 'twin-eave-streams', True, before_shot=align_eave_phase)
                finally:
                    desktop.evaluate("""() => {
                      if (window.__demoOrigPerfNow) {
                        performance.now = window.__demoOrigPerfNow;
                        delete window.__demoOrigPerfNow;
                      }
                    }""")
        editor_shots = [name for name in ('twin-editor', 'twin-awning-editor', 'twin-awning-box-editor', 'twin-posts') if name in shots]
        if editor_shots:
            # The panel shell latches its flags in session storage. Keep the
            # editor's adult session separate while reusing the same browser
            # and one editor page across the four read-only piece shots,
            # resetting selection, camera, level, time and scroll before each.
            browser = desktop.context.browser
            with browser.new_context(viewport=dict(width=1600, height=900),
                    device_scale_factor=1, reduced_motion='reduce', timezone_id=DEMO_TIMEZONE,
                    service_workers='block') as editor_context:
                editor = editor_context.new_page()
                prepare(editor)
                noon = now.replace(hour=12, tzinfo=timezone.utc).isoformat()
                with _shot_stage(editor_shots[0], 'editor', timeout=TWIN_READY_TIMEOUT):
                    H.open_editor(editor, served, timeout=TWIN_READY_TIMEOUT)  # cold start on an empty profile
                    _wait_surface(editor, editor_shots[0])
                    baseline = editor.evaluate("""() => {
                      const v = window.__twin;
                      return {
                        camera: v.cameraState(),
                        level: v.levels?.snapshot ? v.levels.snapshot() : null,
                        time: v.state?.time ?? null,
                      };
                    }""")
                for shot in editor_shots:
                    piece_id = 'demo-awning' if shot.startswith('twin-awning-') else 'front-porch' if shot == 'twin-posts' else 'r1'
                    with _shot_stage(shot, 'editor', timeout=READY_TIMEOUT):
                        editor.evaluate("""({baseline, noon}) => {
                          window.__twinEditor?.selectionStore?.clear?.();
                          const v = window.__twin;
                          if (baseline.level && v.levels?.go) {
                            const target = { level: baseline.level.level };
                            if (baseline.level.building) target.building = baseline.level.building;
                            if (baseline.level.floor) target.floor = baseline.level.floor;
                            if (baseline.level.room) target.room = baseline.level.room;
                            v.levels.go(target, { immediate: true });
                          }
                          if (baseline.time !== null && v.setTime) v.setTime(baseline.time);
                          v.setClock(noon);
                          v.setCameraState(baseline.camera);
                          for (const id of ['piece-card', 'properties-content', 'dock-properties', 'editor-sidebar', 'scene-tree', 'dock-pane-scene']) {
                            const node = document.getElementById(id);
                            if (node) node.scrollTop = 0;
                          }
                        }""", dict(baseline=baseline, noon=noon))
                        editor.wait_for_function("() => !window.__editor?.selected?.()", timeout=READY_TIMEOUT)
                        editor.evaluate("id => window.__editor.clickPiece(id, 'synth-house')", piece_id)
                        editor.wait_for_function("id => window.__editor?.selected?.()?.pieceId === id", arg=piece_id, timeout=READY_TIMEOUT)
                        editor.wait_for_selector('#piece-card', state='visible', timeout=READY_TIMEOUT)
                        editor.evaluate("""() => {
                          for (const id of ['piece-card', 'properties-content', 'dock-properties', 'editor-sidebar']) {
                            const node = document.getElementById(id);
                            if (node) node.scrollTop = 0;
                          }
                        }""")
                    if shot.startswith('twin-awning-'):
                        label = 'Support kind' if shot == 'twin-awning-editor' else 'Ceiling underneath'
                        editor.wait_for_selector(f'[aria-label="{label}"]', state='visible', timeout=READY_TIMEOUT)
                    save(editor, shot, True)
        if 'twin-lit-models' in shots:
            from tools.demo_seed import DEMO_LAMP_ENTITY, furnish_demo_room
            browser = desktop.context.browser
            fake = data.get('_fake')
            prev_moonbeam = fake.states.get('light.demo_moonbeam', {}).get('state') if fake else None
            if fake and 'light.demo_moonbeam' in fake.states:
                # Keep the unplaced ceiling lantern off so only the baked floor lamp lights the room.
                fake.states['light.demo_moonbeam']['state'] = 'off'
            try:
                with _shot_stage('twin-lit-models', 'furniture seed'):
                    furnish_demo_room()
                with browser.new_context(viewport=dict(width=1600, height=900),
                        device_scale_factor=1, reduced_motion='reduce', timezone_id=DEMO_TIMEZONE,
                        service_workers='block') as bake_context:
                    editor = bake_context.new_page()
                    prepare(editor)
                    editor_timeout = max(READY_TIMEOUT, 30000)
                    with _shot_stage('twin-lit-models', 'editor for lighting bake', timeout=editor_timeout):
                        H.open_editor(editor, served, timeout=editor_timeout)
                        editor.wait_for_function(
                            "() => !!(window.__twin?.bake && /^Lighting /.test(document.querySelector('#twin-bake-controls output')?.textContent || ''))",
                            timeout=editor_timeout)
                    with _shot_stage('twin-lit-models', 'lighting bake', timeout=BAKE_TIMEOUT):
                        editor.get_by_role('button', name='Bake lighting', exact=True).click(timeout=READY_TIMEOUT)
                        editor.wait_for_function(
                            """(lamp) => {
                              const b = window.__twin?.bake;
                              if (!b) return false;
                              const st = b.state();
                              return !!st?.key && !st.baking && (b.fresh() || []).includes(lamp);
                            }""",
                            arg=DEMO_LAMP_ENTITY, timeout=BAKE_TIMEOUT)
                with browser.new_context(viewport=dict(width=1600, height=900),
                        device_scale_factor=1, reduced_motion='reduce', timezone_id=DEMO_TIMEZONE,
                        service_workers='block') as viewer_context:
                    viewer = viewer_context.new_page()
                    prepare(viewer, 'family')
                    navigate(viewer, 'twin-lit-models', 'house/twin?tier=high&test=1&panel=true&kiosk=true')
                    with _shot_stage('twin-lit-models', 'night floor cutaway and model light', timeout=BAKE_TIMEOUT):
                        viewer.evaluate("""(pose) => {
                          const v = window.__twin;
                          v.levels.go({ building: 'synth-house', floor: 'L1' }, { immediate: true });
                          v.setTime('night');
                          v.setNightBrightness(0, { persist: false });
                          v.controls.minPolarAngle = 0;
                          v.controls.maxPolarAngle = Math.PI * 0.5;
                          v.controls.minDistance = 0.2;
                          v.controls.maxDistance = 1e6;
                          v.setCameraState(pose);
                          v.render();
                        }""", LIT_MODELS_CAMERA)
                        viewer.wait_for_function(
                            """(lamp) => {
                              const b = window.__twin?.bake;
                              return !!b && (b.fresh() || []).includes(lamp)
                                && (b.models?.stats?.()?.bricks || 0) >= 3;
                            }""",
                            arg=DEMO_LAMP_ENTITY, timeout=BAKE_TIMEOUT)
                    with _shot_stage('twin-lit-models', 'model light warmup', timeout=60000):
                        _ready_evaluate(viewer, 'window.__twin.bake.models.warm()', timeout=60000)
                        viewer.evaluate('() => window.__twin.render()')
                    save(viewer, 'twin-lit-models', True)
            finally:
                if fake and prev_moonbeam is not None and 'light.demo_moonbeam' in fake.states:
                    fake.states['light.demo_moonbeam']['state'] = prev_moonbeam


def _worker(out, shots):
    """Install the tested guard BEFORE importing any Chauffeur service."""
    from tools.demo_isolation import fresh_data_folder, worker_isolation
    directory = fresh_data_folder()
    with worker_isolation(directory, out, permanent=True) as guard:
        from tools.demo_seed import demo_morning
        now = demo_morning()
        _run_worker(out, shots, now, guard)


def _run_worker(out, shots, now, guard):
    served = None
    try:
        from contextlib import asynccontextmanager
        from tools.demo_seed import seed
        import house_editor_model_harness as H
        data, fake = seed(now.date())
        data['capture_time'] = now.isoformat()
        data['_isolation'] = guard
        data['_fake'] = fake
        from services import storage
        H.PARENT = dict(data['members'][0])
        token = storage.create_member_token('avery')
        data['panel_token'] = storage.enrol_device_token('demo-panel', data['panel_name'], by_member='avery')
        H.STATE['token'] = token
        import main
        @asynccontextmanager
        async def quiet_lifespan(app):
            yield  # no polling, paid agents, feed refreshes or real integrations
        main.app.router.lifespan_context = quiet_lifespan
        main.trigger_background_refresh = lambda *a, **kw: None
        main.refresh_schedule_logic = lambda *a, **kw: copy.deepcopy(data['schedule'])
        from services import home_board
        build_board = home_board.build
        home_board.build = lambda *a, **kw: build_board(*a, **dict(kw, now=now.replace(tzinfo=None)))
        served = H.serve(seed_fn=lambda: None)  # already seeded, never open H.HOUSEHOLD
        if served is None:
            raise RuntimeError('Playwright is not installed')
        # Load extension modules (notably pandas' datetime C API) before
        # freezing wall clocks. Runtime timers remain real and bounded.
        from tools.demo_isolation import fixed_clock
        with fixed_clock(now):
            _capture_pages(served, data, token, Path(out), shots)
    except BaseException as error:
        Path(os.environ['CHAUFFEUR_DATA_DIR'], 'capture-error.txt').write_text(
            ' '.join(str(error).split()) or type(error).__name__, encoding='utf-8')
        raise SystemExit(1)
    finally:
        if served is not None:
            served.stop()


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--out')
        parser.add_argument('--shot', action='append', default=[])
        parser.add_argument('--list', action='store_true')
        # Validate after --list so listing never depends on a capture deadline.
        parser.add_argument('--timeout', default='82', metavar='SECONDS',
                            help='worker deadline in seconds (30-600; default: 82)')
        args = parser.parse_args(argv)
        unknown = [name for name in args.shot if name not in ALL_SHOTS]
        if unknown:
            raise ValueError('unknown shot: ' + unknown[0])
        if args.list:
            print('\n'.join([*SHOTS, *(f'{name} (opt-in)' for name in OPT_IN_SHOTS)]))
            return 0
        try:
            timeout = int(args.timeout)
        except ValueError:
            raise ValueError('--timeout must be an integer from 30 to 600 seconds') from None
        if not 30 <= timeout <= 600:
            raise ValueError('--timeout must be an integer from 30 to 600 seconds')
        if not args.out:
            raise ValueError('--out is required')
    except ValueError as error:
        print('demo_capture: ' + ' '.join(str(error).split()), file=sys.stderr)
        return 2
    try:
        capture(args.out, list(dict.fromkeys(args.shot)) or list(SHOTS), timeout=timeout)
        return 0
    except BaseException as error:
        print('demo_capture: ' + (' '.join(str(error).split()) or type(error).__name__), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
