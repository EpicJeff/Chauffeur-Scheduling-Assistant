"""Fail-closed demo boundaries, using only planted decoys and no browser."""
from contextlib import nullcontext
from collections import Counter
import json
import errno
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class DemoIsolationTests(unittest.TestCase):
    def child(self, code, **env):
        result = subprocess.run([sys.executable, '-B', '-c', code], cwd=ROOT,
                                env=dict(os.environ, **env), text=True, capture_output=True, timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_environment_allowlist(self):
        from tools.demo_isolation import worker_environment
        with tempfile.TemporaryDirectory(prefix='chauffeur_demo_') as data:
            inherited = dict(os.environ, HA_TOKEN='DECOY', SUPERVISOR_TOKEN='DECOY',
                             MAPBOX_API_KEY='DECOY', HOME_LOCATION='DECOY',
                             GOOGLE_APPLICATION_CREDENTIALS='DECOY', PYTHONPATH='DECOY',
                             UNKNOWN_FUTURE_SECRET='DECOY', HTTP_PROXY='DECOY')
            env = worker_environment(data, inherited)
            self.assertTrue('DECOY' not in env.values(), 'an excluded variable reached the worker')
            self.assertEqual(env['CHAUFFEUR_DATA_DIR'], data)
            self.assertEqual(env['TEMP'], data)
            self.assertEqual(env['TMP'], data)
            self.assertEqual(env['TZ'], 'EST5EDT' if os.name == 'nt' else 'America/New_York')
            for name in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA'):
                self.assertTrue(Path(env[name]).is_relative_to(data), name)
            if os.name == 'nt':
                self.assertIn('SYSTEMROOT', {name.upper() for name in env})

    def test_browser_requests_and_websockets_are_local_only(self):
        from tools.demo_capture import _restrict_browser
        context = Mock()
        guard = SimpleNamespace(counts=Counter(), blocked=Counter())
        _restrict_browser(context, SimpleNamespace(port=12345), guard)
        request = context.route.call_args.args[1]
        websocket = context.route_web_socket.call_args.args[1]
        for url, allowed in (('http://127.0.0.1:12345/app', True),
                             ('https://outside.invalid/tile', False),
                             ('http://127.0.0.1:12346/app', False), ('file:///decoy', False)):
            route = Mock()
            route.request.url = url
            request(route)
            if allowed:
                route.continue_.assert_called_once()
                route.abort.assert_not_called()
            else:
                route.abort.assert_called_once()
                route.continue_.assert_not_called()
        for url, allowed in (('ws://127.0.0.1:12345/ws', True), ('wss://outside.invalid/ws', False)):
            route = Mock(url=url)
            websocket(route)
            if allowed:
                route.connect_to_server.assert_called_once()
            else:
                route.close.assert_called_once()
                route.connect_to_server.assert_not_called()
        self.assertEqual(guard.blocked, {'browser.request': 3, 'browser.websocket': 1})

    def test_seed_refuses_normal_and_used_folders_without_writes(self):
        self.child(r'''
import os, pathlib, sys, tempfile
from tools.demo_seed import seed
for prefix, used in [('normal_data_', False), ('chauffeur_demo_', True)]:
    with tempfile.TemporaryDirectory(prefix=prefix) as directory:
        folder=pathlib.Path(directory)
        if used: (folder/'decoy.txt').write_text('PLANTED_DECOY')
        before={p.name:p.read_bytes() for p in folder.iterdir()}
        os.environ['CHAUFFEUR_DATA_DIR']=directory
        try: seed()
        except RuntimeError: pass
        else: raise AssertionError('seed admitted a normal or reused folder')
        assert {p.name:p.read_bytes() for p in folder.iterdir()} == before
        assert 'services.storage' not in sys.modules, 'guard ran after service imports'
''')

    def test_shared_worker_guard_blocks_decoys_and_external_sockets(self):
        with tempfile.TemporaryDirectory(prefix='decoy_credentials_') as decoys, \
             tempfile.TemporaryDirectory(prefix='chauffeur_demo_') as data, \
             tempfile.TemporaryDirectory(prefix='chauffeur_demo_stills_') as stage:
            names = ('credentials.json', 'mapbox_api_key.txt', 'serpapi_api_key.txt',
                     'walmart_private_key.pem', 'options.json', '.env', 'chauffeur.sqlite3')
            for name in names:
                (Path(decoys) / name).write_text('PLANTED_DECOY_NEVER_READ', encoding='utf-8')
            output = self.child(r'''
import json, os, pathlib, socket, sqlite3, sys
from tools.demo_isolation import worker_isolation
decoys=pathlib.Path(os.environ['DECOYS'])
data,stage=os.environ['CHAUFFEUR_DATA_DIR'],os.environ['STAGE']
with worker_isolation(data,stage) as guard:
    assert 'HA_TOKEN' not in os.environ and 'UNKNOWN_FUTURE_SECRET' not in os.environ
    from tools.demo_seed import seed
    seeded,_=seed()
    from services import calendar, maps, travel_api, ha_api, walmart, model_pools
    import google.auth
    from google.oauth2.service_account import Credentials
    calendar.CREDENTIALS_FILE=str(decoys/'credentials.json')
    maps.__file__=str(decoys/'services'/'maps.py')
    travel_api.__file__=str(decoys/'services'/'travel_api.py')
    walmart.__file__=str(decoys/'services'/'walmart.py')
    before=guard.blocked.copy()
    assert calendar.get_calendar_service() is None
    assert maps.get_mapbox_api_key() is None
    assert maps.get_map_option('mapbox_api_key','DECOY') is None
    assert travel_api.get_serpapi_key() is None
    assert ha_api._base_and_token() == (None,None)
    assert not walmart.get_credentials()['configured']
    assert not model_pools.api_key_for('openai/demo','pro',{'llm_openai_api_key':'DECOY'})
    assert model_pools.credentials('interactive') == ('','')
    assert not model_pools.has_credentials()
    assert google.auth.default() == (None,None)
    assert Credentials.from_service_account_file(decoys/'credentials.json') is None
    assert guard.blocked == before, 'credential resolver attempted file/network access'
    # Exercise the exact same audit hook used by the live worker. No decoy is
    # ever successfully opened; deliberate probes fail before the OS operation.
    for name in ('credentials.json','mapbox_api_key.txt','serpapi_api_key.txt',
                 'walmart_private_key.pem','options.json','.env'):
        try: open(decoys/name).read()
        except PermissionError: pass
        else: raise AssertionError('decoy was opened')
    for operation in (lambda: sqlite3.connect(decoys/'chauffeur.sqlite3'),
                      lambda: os.scandir(decoys), lambda: os.listdir(decoys)):
        try: operation()
        except PermissionError: pass
        else: raise AssertionError('real-data operation admitted')
    for host in ('203.0.113.9','outside.invalid','::ffff:192.0.2.9'):
        with socket.socket() as client:
            try: client.connect((host,9))
            except OSError: pass
            else: raise AssertionError('external connect admitted')
        try: socket.getaddrinfo(host,80)
        except OSError: pass
        else: raise AssertionError('external DNS admitted')
    for operation in (lambda: socket.gethostbyname('outside.invalid'),
                      lambda: socket.gethostbyaddr('203.0.113.9'),
                      lambda: socket.getnameinfo(('203.0.113.9',80),0)):
        try: operation()
        except OSError: pass
        else: raise AssertionError('secondary DNS resolver admitted')
    with socket.socket() as listener, socket.socket() as client:
        listener.bind(('127.0.0.1',0)); listener.listen(); client.settimeout(5)
        client.connect(listener.getsockname())
        peer,_=listener.accept(); peer.close()
    assert socket.getaddrinfo('127.0.0.1',80)
    for event in ('open','sqlite3.connect','os.scandir','socket.connect','socket.getaddrinfo'):
        assert guard.counts[event]>0 and guard.blocked[event]>0, event
    print(json.dumps(dict(guard.blocked)))
''', DECOYS=decoys, STAGE=stage, CHAUFFEUR_DATA_DIR=data,
                HA_TOKEN='DECOY', UNKNOWN_FUTURE_SECRET='DECOY')
            self.assertGreater(json.loads(output)['socket.connect'], 0)
            for name in names:
                self.assertEqual((Path(decoys) / name).read_text(), 'PLANTED_DECOY_NEVER_READ')

    def test_cleanup_retries_oserror_and_always_restores_environment(self):
        from tools import demo_capture as demo
        original = demo.shutil.rmtree
        before = dict(os.environ)
        with patch.object(demo.shutil, 'rmtree', side_effect=[OSError('busy'), None]) as remove, \
             patch.object(demo.time, 'sleep'):
            with demo.isolated_data() as data:
                self.assertNotEqual(os.environ['CHAUFFEUR_DATA_DIR'], before.get('CHAUFFEUR_DATA_DIR'))
            self.assertEqual(remove.call_count, 2)
        self.assertTrue(dict(os.environ) == before, 'environment was not restored')
        original(data)
        with patch.object(demo.shutil, 'rmtree', side_effect=OSError('still busy')), \
             patch.object(demo.time, 'sleep'):
            with demo.isolated_data() as data:
                pass  # exhausted cleanup retries cannot fail a finished run
        self.assertTrue(dict(os.environ) == before, 'environment was not restored')
        original(data)

    def test_guard_setup_failure_restores_environment(self):
        from tools.demo_isolation import worker_isolation
        before, previous_tempdir = dict(os.environ), tempfile.tempdir
        with tempfile.TemporaryDirectory(prefix='chauffeur_demo_') as data, \
             tempfile.TemporaryDirectory(prefix='chauffeur_demo_stills_') as stage:
            with patch.object(sys, 'addaudithook', side_effect=RuntimeError('cannot install guard')):
                with self.assertRaisesRegex(RuntimeError, 'cannot install guard'):
                    with worker_isolation(data, stage):
                        self.fail('entered without a guard')
            self.assertTrue(dict(os.environ) == before, 'environment was not restored')
            self.assertEqual(tempfile.tempdir, previous_tempdir)

    def test_staging_success_and_failure_remove_all_stale_shots(self):
        from tools import demo_capture as demo
        replace = os.replace
        for mode in ('success', 'worker-fail', 'publish-fail'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as out:
                out = Path(out)
                for name in demo.SHOTS:
                    (out / (name + '.png')).write_bytes(b'stale')
                (out / 'keep.txt').write_text('unrelated')
                untouched = sorted(['keep.txt'] + [name + '.png' for name in demo.SHOTS if name not in ('my-day','plan')])
                process = Mock(returncode=int(mode == 'worker-fail'))
                process.poll.return_value = process.returncode
                def launch(command, **kwargs):
                    stage = Path(command[-3])  # two requested shots
                    self.assertNotEqual(stage, out)
                    def finish(*args, **kw):
                        self.assertEqual(sorted(p.name for p in out.iterdir()), untouched)
                        for name in ('my-day', 'plan'):
                            (stage / (name + '.png')).write_bytes(b'new')
                    process.communicate.side_effect = finish
                    return process
                def publish(source, target):
                    if mode == 'publish-fail' and Path(target).name == 'plan.png':
                        raise OSError('simulated publication failure')
                    return replace(source, target)
                with patch.object(demo.subprocess, 'Popen', side_effect=launch), \
                     patch.object(demo, 'process_tree', return_value=nullcontext(None)), \
                     patch.object(demo.os, 'replace', side_effect=publish), \
                     patch.object(demo, '_resume_worker'), patch.object(demo.os, 'killpg', create=True):
                    if mode != 'success':
                        error = RuntimeError if mode == 'worker-fail' else OSError
                        with self.assertRaises(error):
                            demo.capture(out, ['my-day', 'plan'])
                        self.assertEqual(sorted(p.name for p in out.iterdir()), untouched)
                    else:
                        demo.capture(out, ['my-day', 'plan'])
                        self.assertEqual(sorted(p.name for p in out.iterdir()), sorted(untouched + ['my-day.png','plan.png']))

    def test_publish_cross_device_and_partial_failure(self):
        from tools import demo_capture as demo
        replace = os.replace
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as out:
                out = Path(out)
                process = Mock(returncode=0)
                process.poll.return_value = 0
                local_renames = []
                def launch(command, **kwargs):
                    stage = Path(command[-3])
                    def finish(*args, **kwargs):
                        for name in ('my-day', 'plan'):
                            (stage / (name + '.png')).write_bytes(b'new')
                    process.communicate.side_effect = finish
                    return process
                def same_device(source, target):
                    if Path(source).parent != Path(target).parent:
                        error = OSError(errno.EXDEV, 'simulated cross-drive rename')
                        error.winerror = 17
                        raise error
                    self.assertTrue(Path(source).name.startswith('.chauffeur-demo-'))
                    self.assertEqual(Path(source).parent, out)
                    local_renames.append(target)
                    if fail and len(local_renames) == 2:
                        raise OSError('simulated second rename failure')
                    return replace(source, target)
                with patch.object(demo.subprocess, 'Popen', side_effect=launch), \
                     patch.object(demo, 'process_tree', return_value=nullcontext(None)), \
                     patch.object(demo, '_resume_worker'), patch.object(demo.os, 'killpg', create=True), \
                     patch.object(demo.os, 'replace', side_effect=same_device):
                    if fail:
                        with self.assertRaises(OSError):
                            demo.capture(out, ['my-day', 'plan'])
                        self.assertEqual(list(out.iterdir()), [])
                    else:
                        demo.capture(out, ['my-day', 'plan'])
                        self.assertEqual(sorted(p.name for p in out.iterdir()), ['my-day.png', 'plan.png'])
                self.assertEqual(len(local_renames), 2)

    def test_single_shot_preserves_unrequested_stills(self):
        from tools import demo_capture as demo
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as out:
                out = Path(out)
                for name in demo.SHOTS:
                    (out / (name + '.png')).write_bytes(b'stale')
                def worker(*args):
                    (out / 'plan.png').write_bytes(b'new')
                    if fail:
                        raise RuntimeError('simulated failure')
                with patch.object(demo, '_capture_staged', side_effect=worker):
                    if fail:
                        with self.assertRaises(RuntimeError): demo.capture(out, ['plan'])
                    else:
                        demo.capture(out, ['plan'])
                for name in demo.SHOTS:
                    path = out / (name + '.png')
                    if name == 'plan':
                        if fail: self.assertFalse(path.exists())
                        else: self.assertEqual(path.read_bytes(), b'new')
                    else:
                        self.assertEqual(path.read_bytes(), b'stale')

    def test_worker_installs_guard_before_service_imports(self):
        from contextlib import contextmanager
        from tools import demo_capture as demo, demo_isolation as isolation
        original_guard, add_hook = isolation.worker_isolation, sys.addaudithook
        installed = []
        def check(hook):
            self.assertFalse(any(name == 'main' or name == 'services' or name.startswith('services.')
                                 for name in sys.modules), 'service loaded before the isolation hook')
            installed.append(True)
            add_hook(hook)
        @contextmanager
        def one_run(*args, **kwargs):
            kwargs['permanent'] = False
            with original_guard(*args, **kwargs) as guard:
                yield guard
        with demo.isolated_data() as data, patch.object(sys, 'addaudithook', side_effect=check), \
             patch.object(isolation, 'worker_isolation', side_effect=one_run), \
             patch.object(demo, '_run_worker') as run:
            demo._worker(data, ['plan'])
            run.assert_called_once()
        self.assertEqual(installed, [True], 'worker never installed the isolation audit hook')

    def test_preloaded_service_is_refused(self):
        from tools.demo_isolation import worker_isolation
        for name in ('main', 'services.decoy'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix='chauffeur_demo_') as data:
                with patch.dict(sys.modules, {name: SimpleNamespace()}):
                    with self.assertRaisesRegex(RuntimeError, 'before service imports'):
                        with worker_isolation(data, data):
                            self.fail('admitted a preloaded service')

    def test_async_connects_stop_before_os_interceptor(self):
        self.child(r'''
import asyncio, os, socket, tempfile
from unittest.mock import patch
from tools.demo_isolation import worker_isolation
from asyncio.selector_events import BaseSelectorEventLoop
classes=[asyncio.SelectorEventLoop]
if os.name=='nt':
    from asyncio.windows_events import IocpProactor
    classes.append(asyncio.ProactorEventLoop)
for loop_class in classes:
    loop=loop_class()
    reached=[]
    probing=[False]
    original_selector=BaseSelectorEventLoop._sock_connect
    def below_selector(self,*args):
        if probing[0]:
            reached.append('selector OS interceptor'); raise AssertionError('guard bypassed')
        return original_selector(self,*args)
    if os.name=='nt':
        original_iocp=IocpProactor._register_with_iocp
        def below_iocp(self,*args):
            if probing[0]:
                reached.append('proactor OS interceptor'); raise AssertionError('guard bypassed')
            return original_iocp(self,*args)
    async def exercise(guard):
        for host,family in [('203.0.113.9',socket.AF_INET),('2001:db8::9',socket.AF_INET6)]:
            probing[0]=True
            try:
                try: await asyncio.open_connection(host,9,family=family)
                except PermissionError: pass
                else: raise AssertionError('async external connect admitted')
                with socket.socket(family) as sock:
                    sock.setblocking(False)
                    try: await loop.sock_connect(sock,(host,9))
                    except PermissionError: pass
                    else: raise AssertionError('sock_connect admitted')
                    if hasattr(loop,'_proactor'):
                        try: await loop._proactor.connect(sock,(host,9))
                        except PermissionError: pass
                        else: raise AssertionError('direct proactor connect admitted')
            finally: probing[0]=False
        assert not reached, 'OS interceptor reached; no actual external traffic was sent'
        assert guard.blocked['socket.connect']>=4, guard.blocked
        # Exercise real loopback I/O after the refused attempts.
        server=await asyncio.start_server(lambda r,w:w.close(),'127.0.0.1',0)
        try:
            reader,writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1])
            writer.close(); await writer.wait_closed()
        finally:
            server.close(); await server.wait_closed()
    try:
        with tempfile.TemporaryDirectory(prefix='chauffeur_demo_') as data:
            with patch.object(BaseSelectorEventLoop,'_sock_connect',below_selector):
                if os.name=='nt':
                    with patch.object(IocpProactor,'_register_with_iocp',below_iocp):
                        with worker_isolation(data,data) as guard:
                            loop.run_until_complete(exercise(guard))
                else:
                    with worker_isolation(data,data) as guard:
                        loop.run_until_complete(exercise(guard))
    finally: loop.close()
print('selector/proactor IPv4, IPv6 refusal and real loopback passed')
''')

    def test_windows_local_time_and_original_datetime_instances(self):
        self.child(r'''
import datetime as dt, os, time
from tools.demo_isolation import fixed_clock
from zoneinfo import ZoneInfo
assert time.localtime(dt.datetime(2024,1,15,2,30,tzinfo=dt.timezone.utc).timestamp())[:4] == (2024,1,14,21)
original_datetime,original_date=dt.datetime,dt.date
for stamp,expected,dst in [('2024-01-15T02:30:00+00:00',(2024,1,14,21),0),
                          ('2024-07-15T02:30:00+00:00',(2024,7,14,22),1),
                          ('2024-03-10T06:30:00+00:00',(2024,3,10,1),0),
                          ('2024-03-10T07:30:00+00:00',(2024,3,10,3),1),
                          ('2024-11-03T05:30:00+00:00',(2024,11,3,1),1),
                          ('2024-11-03T06:30:00+00:00',(2024,11,3,1),0)]:
    instant=original_datetime.fromisoformat(stamp)
    moment=instant.astimezone(ZoneInfo('America/New_York'))
    naive=original_datetime(*expected,fold=moment.fold)
    with fixed_clock(moment):
        assert isinstance(naive,dt.datetime), 'original datetime rejected'
        assert isinstance(naive.date(),dt.date), 'original date rejected'
        assert dt.datetime.fromtimestamp(instant.timestamp()).timetuple()[:4] == expected
        assert original_datetime.fromtimestamp(instant.timestamp()).timetuple()[:4] == expected
        assert time.localtime(instant.timestamp())[:4] == expected
        assert time.localtime(instant.timestamp()).tm_isdst == dst
        assert time.localtime()[:3] == expected[:3]
        assert naive.astimezone().date() == moment.date()
        assert naive.astimezone().utcoffset() == moment.utcoffset()
        assert dt.datetime(*expected,fold=moment.fold).astimezone().utcoffset() == naive.astimezone().utcoffset()
        assert dt.datetime.now().date() == moment.date()
print('Windows CRT local-time paths and DST boundaries passed')
''', TZ='EST5EDT' if os.name=='nt' else 'America/New_York')

    def test_missing_resolver_fails_capture_with_one_line(self):
        from tools import demo_capture as demo
        from contextlib import redirect_stderr
        import io
        original = subprocess.Popen
        def launch(command, **kwargs):
            command = list(command)
            index = command.index('-c') + 1
            injection = ("from tools import demo_isolation as iso; "
                         "iso.CREDENTIAL_RESOLVERS['services.maps']['renamed_resolver_decoy']=lambda:None; "
                         "from tools import demo_capture as demo; "
                         "demo._capture_pages=lambda *a:(_ for _ in ()).throw(RuntimeError('browser forbidden')); ")
            command[index] = command[index].replace('sys.stdin.read(1);', injection+'sys.stdin.read(1);')
            return original(command, **kwargs)
        with tempfile.TemporaryDirectory() as out, patch.object(demo.subprocess,'Popen',side_effect=launch):
            errors = io.StringIO()
            with redirect_stderr(errors):
                result = demo.main(['--timeout','170','--out',out,'--shot','plan'])
            self.assertEqual(result,1)
            self.assertEqual(len(errors.getvalue().splitlines()),1)
            self.assertTrue(errors.getvalue().startswith('demo_capture: '))
            self.assertIn('renamed_resolver_decoy',errors.getvalue())
            self.assertEqual(list(Path(out).iterdir()),[])

    @unittest.skipUnless(os.name == 'nt', 'Windows suspended-worker contract')
    def test_worker_assigned_before_resume(self):
        from tools import demo_capture as demo
        order = []
        process = Mock(returncode=1)
        process.poll.return_value = 1
        def launch(*args, **kw):
            self.assertTrue(kw['creationflags'] & 0x4)
            self.assertNotIn('HA_TOKEN', kw['env'])
            self.assertIn('-I', args[0])
            order.append('suspended')
            return process
        def assign(child):
            self.assertIs(child, process)
            order.append('assigned')
        with tempfile.TemporaryDirectory() as out, \
             patch.object(demo.subprocess, 'Popen', side_effect=launch), \
             patch.object(demo, 'process_tree', return_value=nullcontext(assign)), \
             patch.object(demo, '_resume_worker', side_effect=lambda child: order.append('resumed')):
            with self.assertRaisesRegex(RuntimeError, 'capture worker failed'):
                demo.capture(out, ['my-day'])
        self.assertEqual(order, ['suspended', 'assigned', 'resumed'])

    def test_evening_date_and_server_clock(self):
        self.child(r'''
import datetime
from tools.demo_seed import demo_morning, household, DEMO_TIMEZONE
from tools.demo_isolation import fixed_clock
from zoneinfo import ZoneInfo
instant=datetime.datetime.fromisoformat('2024-01-15T02:30:00+00:00')
morning=demo_morning(instant)
assert morning.isoformat() == '2024-01-14T08:12:00-05:00'
assert morning.astimezone(ZoneInfo(DEMO_TIMEZONE)).date().isoformat() == '2024-01-14'
with fixed_clock(morning):
    assert datetime.datetime.now().isoformat() == '2024-01-14T08:12:00'
    assert datetime.date.today().isoformat() == '2024-01-14'
    assert household()['schedule']['events'][0]['start'].startswith('2024-01-14')
    assert datetime.datetime.now(datetime.timezone.utc).isoformat() == '2024-01-14T13:12:00+00:00'
assert datetime.datetime is not None
''')


if __name__ == '__main__':
    unittest.main()
