"""Offline page lookup acceptance tests. Run as a plain script."""
import json
import socket
import threading
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch
from harness import check
from services import storage, page_lookup as p, net_guard, browse, twin_material_sources as twin
RENDER_PAGE = browse.render_page

HTML = '''<title>Fallback</title><meta property="og:title" content="Party shoes">
<meta property="og:site_name" content="Test Store"><script type="application/ld+json">
{"@graph":[{"@type":["Thing","Product"],"image":[{"url":"/shoe.png"}],
"offers":{"@type":"Offer","price":"79","priceCurrency":"USD","availability":"https://schema.org/InStock"}}]}</script>'''

class Response:
    def __init__(self, status=200, body=HTML, headers=None):
        self.status_code = status
        self.content = body.encode() if isinstance(body, str) else body
        self.headers = headers or {'Content-Type': 'text/html'}
        self.encoding = 'utf-8'
    def iter_content(self, chunk_size=65536):
        yield self.content
    def close(self):
        pass

def public(host, port, **kw):
    address = host if host in ('127.0.0.1', '192.168.1.10', '::1') else '93.184.216.34'
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))]

def _fresh():
    storage.lookups_table.truncate()
    storage.get_settings = lambda: {}

def scenario_extracts_jsonld_product():
    d = p.extract(HTML, 'https://store.test/item')
    check((d['title'], d['store'], d['image_url'], d['price'], d['currency'], d['available']) ==
          ('Party shoes', 'Test Store', 'https://store.test/shoe.png', 79.0, 'USD', True), d)

def scenario_meta_tag_price_fallback():
    d = p.extract('<meta property="product:price:amount" content="12.50"><meta property="product:price:currency" content="EUR">', 'https://store.test')
    check(d['price'] == 12.5 and d['currency'] == 'EUR', d)

def scenario_no_price_without_structured_data():
    check(p.extract('<title>Plain</title><body>$79</body>', 'https://store.test')['price'] is None, 'body is not a price source')

def scenario_rejects_non_http_urls():
    d = p.extract('<meta property="og:image" content="javascript:x"><link rel="canonical" href="javascript:x">', 'https://store.test')
    check(d['image_url'] is None and d['canonical'] is None, d)
    check(p.look_up_page('javascript:x', 'm')['status'] == 'error', 'unsafe input')

def scenario_refuses_private_and_redirect_to_private():
    _fresh()
    calls = []
    p.requests.get = lambda *a, **k: Response(302, '', {'Location': 'http://127.0.0.1/'})
    browse.render_page = lambda *a, **k: calls.append(a)
    for url in ('http://127.0.0.1/', 'http://192.168.1.10/', 'http://localhost:8099/', 'https://store.test/item'):
        check(p.look_up_page(url, 'm')['status'] == 'error', url)
    check(not calls and not p.for_mission('m'), 'no fallback or records after guard refusal')

def scenario_chromium_fallback_on_403():
    _fresh()
    p.requests.get = lambda *a, **k: Response(403)
    browse.render_page = lambda *a, **k: ('https://store.test/final', HTML)
    r = p.look_up_page('https://store.test/item', 'm')
    check(r['status'] == 'ok', r)
    check(p.get(r['lookup']['lookup'])['final_url'] == 'https://store.test/final', r)
    check(p.delete_for_mission('m', {r['lookup']['lookup']}) == 0, 'kept lookup survives')

PLAIN_HTML = '<title>Plain shoes</title><meta property="og:image" content="/plain.png"><meta property="og:site_name" content="Plain Store">'

def scenario_plain_200_kept_when_render_fails():
    _fresh()
    with patch.object(p.requests, 'get', return_value=Response(body=PLAIN_HTML)), \
         patch.object(browse, 'render_page', return_value=None):
        r = p.look_up_page('https://store.test/plain', 'm')
    check(r['status'] == 'ok', r)
    record = p.get(r['lookup']['lookup'])
    check((record['title'], record['image_url'], record['store'], record['final_url']) ==
          ('Plain shoes', 'https://store.test/plain.png', 'Plain Store', 'https://store.test/plain'), record)

def scenario_plain_200_kept_over_interstitial():
    _fresh()
    with patch.object(p.requests, 'get', return_value=Response(body=PLAIN_HTML)), \
         patch.object(browse, 'render_page', return_value=('https://store.test/challenge', '<title>Just a moment...</title>')):
        r = p.look_up_page('https://store.test/plain', 'm')
    check(r['status'] == 'ok', r)
    record = p.get(r['lookup']['lookup'])
    check(record['title'] == 'Plain shoes' and record['store'] == 'Plain Store' and
          record['image_url'] == 'https://store.test/plain.png' and record['final_url'] == 'https://store.test/plain', record)

def scenario_render_used_when_it_adds_product_data():
    _fresh()
    with patch.object(p.requests, 'get', return_value=Response(body='<title>Store shell</title>')), \
         patch.object(browse, 'render_page', return_value=('https://store.test/product', HTML)):
        r = p.look_up_page('https://store.test/plain', 'm')
    check(r['status'] == 'ok', r)
    record = p.get(r['lookup']['lookup'])
    check(record['price'] == 79 and record['image_url'] == 'https://store.test/shoe.png' and
          record['final_url'] == 'https://store.test/product', record)

def scenario_403_render_fails_is_error():
    for status in (401, 403, 429):
        for rendered in (None, ('https://store.test', '<html></html>'),
                         ('https://store.test', '<script type="application/ld+json">{"@type":"Product"}</script>')):
            _fresh()
            with patch.object(p.requests, 'get', return_value=Response(status)), \
                 patch.object(browse, 'render_page', return_value=rendered):
                r = p.look_up_page('https://store.test/plain', 'm')
            check(r['status'] == 'error' and not p.for_mission('m'), r)

def scenario_render_image_improvement_needs_a_title():
    for title in ('', '<title>Just a moment...</title>', '<title>Plain shoes</title>'):
        _fresh()
        html = title + '<meta property="og:image" content="/render.png">'
        with patch.object(p.requests, 'get', return_value=Response(body='<title>Plain shoes</title>')), \
             patch.object(browse, 'render_page', return_value=('https://store.test/render', html)):
            r = p.look_up_page('https://store.test/plain', 'm')
        check(r['status'] == 'ok', r)
        record = p.get(r['lookup']['lookup'])
        check(record['title'] == 'Plain shoes' and record['image_url'] ==
              ('https://store.test/render.png' if title == '<title>Plain shoes</title>' else None), record)

def scenario_empty_200_shell_with_failed_render_is_error():
    for html in ('<html><div id="app"></div></html>', '<body>Loading the app...</body>'):
        _fresh()
        with patch.object(p.requests, 'get', return_value=Response(body=html)), \
             patch.object(browse, 'render_page', return_value=None):
            r = p.look_up_page('https://store.test/shell', 'm')
        check(r == {'status': 'error', 'note': 'The page could not be read.'}, r)
        check(not p.for_mission('m'), 'unusable shell must not consume a lookup')

def scenario_403_challenge_render_is_error():
    titles = ('just a moment', 'attention required', 'access denied', 'are you a robot',
              'please verify you are a human', 'checking your browser', 'pardon our interruption')
    for status in (401, 403, 429):
        for title in titles:
            for meta in ('', '<meta property="product:price:amount" content="12"><meta property="product:price:currency" content="USD">'):
                _fresh()
                html = f'<title>  {title.upper()}...  </title><meta property="og:image" content="/challenge.png">' + meta
                with patch.object(p.requests, 'get', return_value=Response(status)), \
                     patch.object(browse, 'render_page', return_value=('https://store.test/challenge', html)):
                    r = p.look_up_page('https://store.test/item', 'm')
                check(r == {'status': 'error', 'note': 'The page could not be read.'} and not p.for_mission('m'), (status, title, r))

def scenario_200_challenge_render_never_replaces_plain():
    challenge = '<title> Just a moment...</title><meta property="og:image" content="/challenge.png">' + \
                '<meta property="product:price:amount" content="12"><meta property="product:price:currency" content="USD">'
    for plain in (PLAIN_HTML, '<html></html>'):
        _fresh()
        with patch.object(p.requests, 'get', return_value=Response(body=plain)), \
             patch.object(browse, 'render_page', return_value=('https://store.test/challenge', challenge)):
            r = p.look_up_page('https://store.test/plain', 'm')
        if plain == PLAIN_HTML:
            check(r['status'] == 'ok', r)
            record = p.get(r['lookup']['lookup'])
            check((record['title'], record['image_url'], record['price'], record['final_url']) ==
                  ('Plain shoes', 'https://store.test/plain.png', None, 'https://store.test/plain'), record)
        else:
            check(r['status'] == 'error' and not p.for_mission('m'), r)

def scenario_403_product_render_is_ok():
    cases = [(HTML, True),
             ('<meta property="product:price:amount" content="0"><meta property="product:price:currency" content="USD">', True),
             ('<title>Venue</title><meta property="og:image" content="/venue.png">', True),
             ('<title>Store shell</title>', False),
             ('<meta property="og:image" content="/logo.png">', False)]
    for html, accepted in cases:
        _fresh()
        with patch.object(p.requests, 'get', return_value=Response(403)), \
             patch.object(browse, 'render_page', return_value=('https://store.test/rendered', html)):
            r = p.look_up_page('https://store.test/item', 'm')
        check((r['status'] == 'ok') == accepted and len(p.for_mission('m')) == int(accepted), (html, r))
        if html == HTML:
            record = p.get(r['lookup']['lookup'])
            check(record['price'] == 79 and record['image_url'] == 'https://store.test/shoe.png', record)

def scenario_cap():
    _fresh()
    for i in range(30):
        storage.lookups_table.insert({'id': str(i), 'mission_id': 'm'})
    check('30 page look-ups' in p.look_up_page('https://store.test', 'm')['note'], 'cap')

def scenario_compact_is_small():
    _fresh()
    p.requests.get = lambda *a, **k: Response()
    r = p.look_up_page('https://store.test/item', 'm')
    check(r['status'] == 'ok' and len(json.dumps(r['lookup'])) < 900, r)

def scenario_twin_guard_unchanged():
    try:
        twin._check_public('http://127.0.0.1/')
    except twin.DownloadError:
        return
    raise AssertionError('twin guard must refuse loopback')

def scenario_render_page_guards_requests_and_closes():
    calls = []; routes = []; private = [False]
    class Session:
        def on(self, name, guard): routes[:] = [guard]
        def send(self, name, args=None):
            calls.append(name)
            if name == 'Page.getFrameTree': return {'frameTree': {'frame': {'id': 'main'}}}
    class Page:
        url = 'https://store.test/final'
        def goto(self, url, **kw):
            check(kw['wait_until'] == 'load', kw)
            calls.append('goto'); routes[0]({'requestId':'first','frameId':'main','resourceType':'Document','request':{'url':url}})
            if private[0]: routes[0]({'requestId':'redirect','redirectedRequestId':'first','frameId':'main','resourceType':'Document','request':{'url':'http://127.0.0.1/'}})
        def wait_for_load_state(self, state, timeout):
            check(state == 'networkidle' and 0 < timeout <= 1500, (state, timeout))
            calls.append('settle')
            from playwright.sync_api import TimeoutError
            raise TimeoutError('Tracker never goes idle')
        def content(self): return HTML
    class Context:
        def route_web_socket(self, pattern, handler):
            check(pattern.fullmatch('ws://127.0.0.1/private'), 'all sockets intercepted')
            calls.append('websocket handler')
            socket_calls = []
            handler(SimpleNamespace(**{name: lambda *a, _name=name, **k: socket_calls.append(_name)
                                       for name in ('connect_to_server', 'close', 'send', 'on_message', 'on_close')}))
            check(not socket_calls, f'WebSocket handler must stay mocked without sync calls: {socket_calls}')
        def new_cdp_session(self, page): return Session()
        def new_page(self): return Page()
        def close(self): calls.append('context closed')
    class Browser:
        def new_context(self, **kw): return Context()
        def close(self): calls.append('browser closed')
    class PW:
        def stop(self): calls.append('stopped')
    old, old_render = browse._render_launch, browse.render_page
    browse.render_page = RENDER_PAGE
    browse._render_launch = lambda: (calls.append('launch') or PW(), Browser())
    try:
        check(browse.render_page('https://store.test') == ('https://store.test/final', HTML), calls)
        check(calls.index('websocket handler') < calls.index('goto'), calls)
        check(calls.count('launch') == calls.count('goto') == 1 and calls[-3:] == ['context closed','browser closed','stopped'], calls)
        private[0] = True
        check(browse.render_page('https://store.test') is None and 'Fetch.failRequest' in calls, 'private browser redirect refused')
        before = calls.count('launch')
        check(browse.render_page('http://127.0.0.1/') is None and calls.count('launch') == before, 'no browser for private initial URL')
    finally: browse._render_launch, browse.render_page = old, old_render

def scenario_refused_image_does_not_fail_render():
    callbacks = {}; failed = []
    class Session:
        def on(self, name, fn): callbacks[name] = fn
        def send(self, name, args=None):
            if name == 'Page.getFrameTree': return {'frameTree': {'frame': {'id':'main'}}}
            if name == 'Fetch.failRequest': failed.append(args['requestId'])
    class Page:
        url = 'https://store.test/final'
        def wait_for_load_state(self, *a, **k): pass
        def goto(self, *a, **k):
            for kind, frame in [('Image','main'), ('Document','child')]:
                callbacks['Fetch.requestPaused']({'requestId':kind, 'resourceType':kind,'frameId':frame,
                                                 'request':{'url':'http://127.0.0.1/tracker'}})
        def content(self): return HTML
    context = SimpleNamespace(new_page=Page, new_cdp_session=lambda page: Session(), close=lambda: None,
                              route_web_socket=lambda *a: None)
    browser = SimpleNamespace(new_context=lambda **k: context, close=lambda: None)
    pw = SimpleNamespace(stop=lambda: None)
    with patch.object(browse, '_render_launch', return_value=(pw,browser)):
        check(RENDER_PAGE('https://store.test') == ('https://store.test/final',HTML), 'subresources must not fail the page')
    check(failed == ['Image','Document'], failed)

def scenario_render_remembers_driver_inside_chromium_launch():
    entered = threading.Event(); release = threading.Event(); stopped = threading.Event(); killed = threading.Event()
    remembered = []; launch_args = []; result = []
    proc = SimpleNamespace(pid=987654, returncode=None)
    browser = SimpleNamespace(close=lambda: None)
    def launch(**kw):
        launch_args.append(kw)
        remembered.append(browse._render_worker.state['process'] is proc)
        entered.set(); release.wait()
        return browser
    pw = SimpleNamespace(chromium=SimpleNamespace(executable_path='fake-bundled', launch=launch), stop=stopped.set,
                         _impl_obj=SimpleNamespace(_connection=SimpleNamespace(_transport=SimpleNamespace(_proc=proc))))
    def kill(state):
        remembered.append(state['process'] is proc)
        killed.set()
    with patch('playwright.sync_api.sync_playwright', return_value=SimpleNamespace(start=lambda: pw)), \
         patch.object(browse, '_system_chromium', return_value='fake-system'), \
         patch.object(browse, '_headless', return_value=True), \
         patch.object(browse, '_launch', side_effect=AssertionError('render must use its own launcher')), \
         patch.object(browse, '_kill_render_driver', side_effect=kill), \
         patch.object(browse, 'RENDER_TIMEOUT_MARGIN_S', 0.03):
        caller = threading.Thread(target=lambda: result.append(RENDER_PAGE('https://store.test', timeout_s=0.03)), daemon=True)
        caller.start()
        try:
            check(entered.wait(0.5), 'Chromium launch was actually entered')
            caller.join(0.5)
            check(not caller.is_alive() and result == [None] and killed.wait(0.5), result)
            check(remembered and all(remembered), 'driver must be captured before the launch block and available to teardown')
            check(launch_args == [{'headless': True, 'args': [f'--window-size={browse.W},{browse.H}'],
                                   'executable_path': 'fake-system'}], launch_args)
        finally:
            release.set(); caller.join(1); stopped.wait(1)

def scenario_render_wall_clock_bounds_goto_and_cleanup():
    for blocked in ('launch', 'goto', 'close'):
        release = threading.Event(); entered = threading.Event(); finished = threading.Event()
        worker_finished = threading.Event()
        result = []; errors = []; killed = []
        def block():
            entered.set()
            release.wait()
        page = SimpleNamespace(url='https://store.test', goto=lambda *a, **k: block() if blocked == 'goto' else None,
                               content=lambda: HTML, wait_for_load_state=lambda *a, **k: None)
        session = SimpleNamespace(on=lambda *a: None, send=lambda *a: {'frameTree': {'frame': {'id':'main'}}})
        context = SimpleNamespace(new_page=lambda: page, new_cdp_session=lambda p: session,
                                  route_web_socket=lambda *a: None,
                                  close=lambda: block() if blocked == 'close' else None)
        pw = SimpleNamespace(stop=worker_finished.set)
        browser = SimpleNamespace(new_context=lambda **k: context, close=lambda: None)
        def launch():
            if blocked == 'launch': block()
            return pw, browser
        def kill(state):
            killed.append(True)
            # Even emergency teardown itself may hang; the caller must still return.
            release.wait()
        def call():
            try: result.append(RENDER_PAGE('https://store.test', timeout_s=0.03))
            except Exception as exc: errors.append(exc)
            finally: finished.set()
        with patch.object(browse, '_render_launch', side_effect=launch), \
             patch.object(browse, 'RENDER_TIMEOUT_MARGIN_S', 0.03), \
             patch.object(browse, '_kill_render_driver', side_effect=kill):
            caller = threading.Thread(target=call, daemon=True)
            start = time.monotonic(); caller.start()
            try:
                check(entered.wait(0.5), f'{blocked} was actually reached')
                check(finished.wait(0.5), f'{blocked} exceeded the whole-render deadline')
                check(time.monotonic() - start < 0.6 and result == [None] and not errors, (result, errors))
                # Teardown is asynchronous and must never hold up the caller.
                for _ in range(100):
                    if killed: break
                    threading.Event().wait(0.001)
                check(killed, 'timed-out browser teardown requested')
            finally:
                release.set(); caller.join(1); worker_finished.wait(1)

def scenario_render_driver_tree_teardown_is_bounded():
    calls = []
    proc = SimpleNamespace(pid=987654, returncode=None, kill=lambda: calls.append('kill'))
    pw = SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(_transport=SimpleNamespace(_proc=proc))))
    state = {'cancelled': threading.Event(), 'process': None}
    browse._render_worker.state = state
    try:
        browse._remember_render_driver(pw)
        check(state['process'] is proc, 'capture the driver before Chromium launch')
        with patch.object(browse.os, 'name', 'nt'), \
             patch.object(browse.subprocess, 'CREATE_NO_WINDOW', 0, create=True), \
             patch.object(browse.subprocess, 'run') as run:
            browse._kill_render_driver(state)
        check(run.call_args.args[0] == ['taskkill','/PID','987654','/T','/F'], run.call_args)
        check(run.call_args.kwargs['timeout'] == 2 and calls == ['kill'], (run.call_args, calls))
        calls.clear()
        # Linux add-on: include browser/grandchildren, leave unrelated processes alone.
        stats = {'/proc/10/stat': '10 (driver) S 1', '/proc/11/stat': '11 (browser) S 10',
                 '/proc/12/stat': '12 (renderer) S 11', '/proc/13/stat': '13 (other) S 1'}
        from io import StringIO
        proc.pid = 10
        with patch.object(browse.os, 'name', 'posix'), patch.object(browse.os, 'listdir', return_value=['10','11','12','13']), \
             patch.object(browse.signal, 'SIGKILL', 9, create=True), \
             patch('builtins.open', side_effect=lambda path: StringIO(stats[path])), \
             patch.object(browse.os, 'kill', side_effect=lambda pid, sig: calls.append(pid)):
            browse._kill_render_driver(state)
        check(calls == [12,11,10,'kill'], calls)
    finally:
        del browse._render_worker.state

def scenario_title_without_product_data_uses_fallback():
    _fresh(); calls=[]
    with patch.object(p.requests,'get',return_value=Response(body='<title>Store app</title>')), \
         patch.object(browse,'render_page',side_effect=lambda u: calls.append(u) or (u,HTML)):
        r=p.look_up_page('https://store.test/app','m')
    check(calls == ['https://store.test/app'] and r['lookup']['price']==79, r)

def scenario_price_meta_does_not_need_fallback():
    _fresh()
    html='<title>Meta</title><meta property="product:price:amount" content="12"><meta property="product:price:currency" content="USD">'
    with patch.object(p.requests,'get',return_value=Response(body=html)), patch.object(browse,'render_page') as render:
        r=p.look_up_page('https://store.test/meta','m')
    check(r['status']=='ok' and r['lookup']['price']==12 and not render.called,r)

def scenario_guard_names_dns_rebinding_limit():
    check('rebind' in net_guard.__doc__.lower(),'guard must document DNS rebinding limit')

def scenario_page_deadline_aborts_slow_chunks_and_redirects():
    _fresh(); clock=[0.0]; closed=[]
    class Slow(Response):
        def iter_content(self, chunk_size=65536):
            for _ in range(2):
                clock[0]+=11
                yield b'<title>Slow</title>'
        def close(self): closed.append(True)
    with patch.object(p,'time',SimpleNamespace(monotonic=lambda:clock[0])), \
         patch.object(p.requests,'get',return_value=Slow()), patch.object(browse,'render_page') as render:
        r=p.look_up_page('https://store.test/slow','m')
    check(r['status']=='error' and 'long' in r['note'].lower() and closed and not render.called,r)
    check(not p.for_mission('m'),'timed out lookups are not stored')
    clock[0]=0; calls=[]
    def redirects(*a,**k):
        calls.append(a);clock[0]+=11
        return Response(302,'',{'Location':'https://store.test/again'})
    with patch.object(p,'time',SimpleNamespace(monotonic=lambda:clock[0])), patch.object(p.requests,'get',side_effect=redirects):
        r=p.look_up_page('https://store.test/slow','m')
    check(r['status']=='error' and 'long' in r['note'].lower() and len(calls)==2,r)

if __name__ == '__main__':
    old = p.requests.get, browse.render_page, net_guard._resolve, twin._resolve
    net_guard._resolve = twin._resolve = public
    failed = 0
    try:
        for name, fn in list(globals().items()):
            if name.startswith('scenario_'):
                try:
                    fn(); print('PASS', name)
                except Exception:
                    failed += 1; print('FAIL', name); traceback.print_exc()
    finally:
        p.requests.get, browse.render_page, net_guard._resolve, twin._resolve = old
    raise SystemExit(bool(failed))
