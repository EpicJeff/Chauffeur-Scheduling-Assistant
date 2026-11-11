"""Live state pushed from Home Assistant (Task 2 of
docs/superpowers/plans/2026-11-11-twin-device-controls.md; spec
docs/superpowers/specs/2026-11-11-twin-device-controls-design.md decision 5;
brief .superpowers/sdd/2026-11-11-twin-device-controls/task-2-brief.md).

No network sockets: Home Assistant's websocket is a fake connection object
patched over `ha_events._connect`, and the SSE route is driven by calling the
ASGI app in-process on one shared event loop (TestClient buffers a whole
response, so it cannot read a stream that never ends; the one loopback pair
left is asyncio's own self-pipe, made once, see _app_loop).

Interfaces assumed (services/ha_events.py):
- `start()`: starts ONE background client when Home Assistant is configured,
  i.e. when `ha_api._ws_url_and_token()` names a url; with none it starts no
  thread and connects to nothing. Calling it again while running changes nothing.
- `stop()`: ends the client (closes the connection, the thread exits).
- `subscribe(entities=None) -> queue.Queue`: each pushed change arrives as
  `{'entity_id': str, 'state': <HA's new_state object, or None when removed>}`;
  with `entities` given, only those ids arrive. `unsubscribe(q)` ends one.
- `_connect(url)`: the seam the tests replace; returns a connection with
  `send(text)`, `recv(timeout=None) -> text` and `close()` (the shape of
  websockets.sync.client's connection, which ha_api.ws_command already uses).
  Auth rides the connection as HA's own protocol: auth_required, auth with the
  token from `_ws_url_and_token()`, auth_ok, then
  `{'id': n, 'type': 'subscribe_events', 'event_type': 'state_changed'}`.
- `BACKOFF_BASE` / `BACKOFF_MAX` (seconds): module constants read at run time;
  the delay between failed connects starts near BACKOFF_BASE and grows (to at
  most BACKOFF_MAX). These tests set 0.1 / 1.0.
- A pushed change is written into `ha_api`'s states cache (the row replaced,
  the cache marked fresh) BEFORE subscribers hear of it.

The route: `GET /api/ha/stream[?area=<area_id>]` (WALL_OR_SERVICE), media type
text/event-stream; every `data:` line is one JSON change shaped like the queue
item above (unnamed SSE events, so `EventSource.onmessage` reads them). Comment
lines (`: ping`) are allowed; nothing else is sent as data. The route takes no
entity list from the URL (Ruling C11, review M4: a house's list overflowed the
ingress request line): the server derives the page's set from the house's
placements, `main._house_stream_entities(area)`, which these tests stand in for
except where the derivation itself is checked. A page may narrow it by area id.
A camera's access token, and the token in its entity_picture, never reach a
subscriber (Ruling C9, review M5); the server's own cache keeps them.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_ha_events.py
"""
import asyncio
import contextlib
import copy
import io
import json
import logging
import os
import queue
import sys
import tempfile
import threading
import time
import traceback
from unittest.mock import patch

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_ha_events_')
for _name in ('HA_BASE_URL', 'HA_TOKEN', 'SUPERVISOR_TOKEN'):
    os.environ.pop(_name, None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from services import auth, ha_api, storage  # noqa: E402

STREAM = '/api/ha/stream'
TOKEN = 'tok-ha'
SERVICE_TOKEN = 'svc-secret-1'
_real_settings = storage.get_settings


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def wait_until(pred, timeout, step=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(step)
    return bool(pred())


def _events():
    from services import ha_events
    return ha_events


# ---------------------------------------------------------------- fake Home Assistant websocket

_CLOSED = object()


class FakeConn:
    """One accepted websocket, in memory. HA's side of the protocol only."""

    def __init__(self, hub):
        self.hub, self.inbox, self.closed = hub, queue.Queue(), False
        self.sub_id = None
        self.authed = False
        self.inbox.put({'type': 'auth_required', 'ha_version': '2026.11.0'})

    def _reply(self, msg):
        self.inbox.put(msg)

    def send(self, text):
        if self.closed:
            from websockets.exceptions import ConnectionClosedError
            raise ConnectionClosedError(None, None)
        msg = json.loads(text)
        kind = msg.get('type')
        if kind == 'auth':
            self.authed = msg.get('access_token') == self.hub.token
            self._reply({'type': 'auth_ok' if self.authed else 'auth_invalid', 'ha_version': '2026.11.0'})
            return
        if not self.authed:
            return
        if kind == 'subscribe_events' and msg.get('event_type') == 'state_changed':
            self.sub_id = msg['id']
            self._reply({'id': msg['id'], 'type': 'result', 'success': True, 'result': None})
        elif kind == 'get_states':
            self._reply({'id': msg['id'], 'type': 'result', 'success': True,
                         'result': copy.deepcopy(list(self.hub.states.values()))})
        elif kind == 'ping':
            self._reply({'id': msg['id'], 'type': 'pong'})
        elif 'id' in msg:
            self._reply({'id': msg['id'], 'type': 'result', 'success': True, 'result': None})

    def recv(self, timeout=None, *args, **kwargs):
        if self.closed and self.inbox.empty():
            from websockets.exceptions import ConnectionClosedError
            raise ConnectionClosedError(None, None)
        try:
            item = self.inbox.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError('timed out waiting for a message')
        if item is _CLOSED:
            from websockets.exceptions import ConnectionClosedError
            raise ConnectionClosedError(None, None)
        return json.dumps(item)

    def __iter__(self):
        from websockets.exceptions import ConnectionClosedOK
        while True:
            try:
                yield self.recv()
            except ConnectionClosedOK:
                return

    def ping(self, *args, **kwargs):
        done = threading.Event()
        done.set()
        return done

    def close(self, *args, **kwargs):
        if not self.closed:
            self.closed = True
            self.inbox.put(_CLOSED)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeHub:
    """Home Assistant's websocket endpoint and its REST /states, in memory."""

    def __init__(self):
        self.token = TOKEN
        self.refuse = False
        self.attempts = []          # (monotonic time, accepted)
        self.conns = []
        self.rest_calls = []
        self.states = {s['entity_id']: s for s in (
            _state('light.kitchen', 'off', brightness=None),
            _state('lock.back', 'locked'),
            _state('switch.other', 'off'),
        )}
        self.orig = {}

    def connect(self, url, *args, **kwargs):
        self.attempts.append((time.monotonic(), not self.refuse))
        if self.refuse:
            raise ConnectionRefusedError('Home Assistant is restarting')
        conn = FakeConn(self)
        self.conns.append(conn)
        return conn

    def live(self):
        return [c for c in self.conns if not c.closed and c.sub_id is not None]

    def subscribed(self, n=1):
        return sum(1 for c in self.conns if c.sub_id is not None) >= n and bool(self.live())

    def push(self, entity_id, state, **attributes):
        old = copy.deepcopy(self.states.get(entity_id))
        new = _state(entity_id, state, **attributes)
        self.states[entity_id] = new
        for conn in self.live():
            conn.inbox.put({'id': conn.sub_id, 'type': 'event', 'event': {
                'event_type': 'state_changed', 'time_fired': '2026-11-11T12:00:00+00:00', 'origin': 'LOCAL',
                'data': {'entity_id': entity_id, 'old_state': old, 'new_state': copy.deepcopy(new)}}})
        return new

    def drop(self):
        """HA goes away: every open connection dies and new ones are refused."""
        self.refuse = True
        for conn in self.conns:
            conn.close()

    def rest(self, method, path, json_body=None, params=None, timeout=None):
        self.rest_calls.append((method, path))
        if method == 'GET' and path == '/states':
            return copy.deepcopy(list(self.states.values()))
        if method == 'GET' and path.startswith('/states/'):
            return copy.deepcopy(self.states.get(path[len('/states/'):]))
        if method == 'GET' and path == '/config':
            return {'version': '2026.11.0'}
        return None

    def install(self):
        ev = _events()
        self.orig = {'_connect': (ev, ev._connect),
                     '_ws_url_and_token': (ha_api, ha_api._ws_url_and_token),
                     '_base_and_token': (ha_api, ha_api._base_and_token),
                     '_request': (ha_api, ha_api._request),
                     'BACKOFF_BASE': (ev, getattr(ev, 'BACKOFF_BASE', None)),
                     'BACKOFF_MAX': (ev, getattr(ev, 'BACKOFF_MAX', None))}
        ev._connect = self.connect
        ev.BACKOFF_BASE, ev.BACKOFF_MAX = 0.1, 1.0
        ha_api._ws_url_and_token = lambda: ('ws://ha.test:8123/api/websocket', TOKEN)
        ha_api._base_and_token = lambda: ('http://ha.test:8123/api', TOKEN)
        ha_api._request = self.rest
        _reset_cache()
        return self

    def uninstall(self):
        try:
            _events().stop()
        finally:
            for name, (owner, value) in self.orig.items():
                if value is not None:
                    setattr(owner, name, value)
            _reset_cache()


def _state(eid, st, **attrs):
    return {'entity_id': eid, 'state': st, 'last_changed': '2026-11-11T12:00:00+00:00',
            'attributes': {'friendly_name': eid.split('.', 1)[1].replace('_', ' ').title(),
                           **{k: v for k, v in attrs.items() if v is not None}}}


def _reset_cache():
    with ha_api._cache_lock:
        ha_api._states_cache.clear()
        ha_api._states_cache.update({'ts': 0.0, 'data': None})


@contextlib.contextmanager
def fake_ha():
    hub = FakeHub().install()
    try:
        yield hub
    finally:
        hub.uninstall()


def started(hub, n=1):
    """start() and wait for the n-th subscription to state_changed."""
    _events().start()
    check(wait_until(lambda: hub.subscribed(n), 3),
          f'the client connects, authenticates and subscribes to state_changed: attempts {hub.attempts}')


# ---------------------------------------------------------------- the app, in-process

_LOOP = {'loop': None}


def _app_loop():
    """ONE event loop for every in-process request, on its own thread.

    Making an event loop on Windows makes a loopback socket pair (asyncio's
    self-pipe), and this machine's loopback drops connections in bursts: a loop
    per request hung one run in five inside socket.accept. So the loop is made
    once, and a try that has not come up in 5 s is abandoned for a fresh one."""
    if _LOOP['loop'] is not None:
        return _LOOP['loop']
    for _ in range(3):
        ready, box = threading.Event(), {}

        def run():
            loop = asyncio.new_event_loop()
            box['loop'] = loop
            ready.set()
            loop.run_forever()
        threading.Thread(target=run, daemon=True, name='test-app-loop').start()
        if ready.wait(5):
            _LOOP['loop'] = box['loop']
            return box['loop']
    raise AssertionError('could not make an event loop (loopback socket pair) in three tries')


class Stream:
    """One GET to the ASGI app on the shared test loop: no socket. The
    response's start and every body chunk are recorded as they are sent, and
    close() is the browser going away (http.disconnect)."""

    def __init__(self, path, headers=()):
        import main
        self.app, self.path, self.headers = main.app, path, list(headers)
        self.status, self.media, self.body, self.ended = None, '', b'', False
        self.error = None
        self.started = threading.Event()
        self.lock = threading.Lock()
        self.loop = self.gone = self.future = None

    async def _main(self):
        self.gone = asyncio.Event()
        path, _, query = self.path.partition('?')
        scope = {'type': 'http', 'http_version': '1.1', 'method': 'GET', 'scheme': 'http', 'path': path,
                 'raw_path': path.encode(), 'root_path': '', 'query_string': query.encode(),
                 'headers': [(k.lower().encode(), v.encode()) for k, v in self.headers],
                 'client': ('192.168.1.40', 50000), 'server': ('testserver', 80), 'state': {}, 'extensions': {}}
        asked = False

        async def receive():
            nonlocal asked
            if not asked:
                asked = True
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            await self.gone.wait()
            return {'type': 'http.disconnect'}

        async def send(message):
            if message['type'] == 'http.response.start':
                self.status = message['status']
                self.media = dict((k.decode().lower(), v.decode()) for k, v in message.get('headers', [])).get(
                    'content-type', '')
                self.started.set()
            elif message['type'] == 'http.response.body':
                with self.lock:
                    self.body += message.get('body', b'')
                if not message.get('more_body'):
                    self.ended = True

        try:
            await self.app(scope, receive, send)
        except BaseException as e:  # recorded; asserted on by the caller
            self.error = e
            raise
        finally:
            self.started.set()

    def open(self):
        self.loop = _app_loop()
        self.future = asyncio.run_coroutine_threadsafe(self._main(), self.loop)
        check(self.started.wait(10), f'{self.path}: the response starts')
        check(self.error is None, f'{self.path}: the app raised {self.error!r}')
        return self

    def text(self):
        with self.lock:
            return self.body.decode('utf-8', 'replace')

    def changes(self):
        """Every `data:` line, parsed."""
        out = []
        for line in self.text().splitlines():
            if line.startswith('data:'):
                out.append(json.loads(line[5:].strip()))
        return out

    def close(self):
        if self.future is None:
            return True
        if not self.future.done() and self.gone is not None:
            self.loop.call_soon_threadsafe(self.gone.set)
        try:
            self.future.result(5)
        except Exception:
            pass
        if not self.future.done():
            self.future.cancel()
            return False
        return True


class People:
    """Enforcement on; a parent, a panel and the service token."""

    def __enter__(self):
        for mid, role in (('mum', 'parent'), ('kid', 'child')):
            if not storage.get_member(mid):
                storage.add_member({'id': mid, 'name': mid.title(), 'role': role, 'status': 'active'})
        self.mum_token = storage.create_member_token('mum', proof='password', minted_on='personal')
        self.panel = {'X-Device-Token': storage.enrol_device_token('panel-1', 'Kitchen panel', by_member='mum')}
        self.service = {'X-Service-Token': SERVICE_TOKEN}
        self.patch = patch.object(storage, 'get_settings', side_effect=lambda: {
            **_real_settings(), 'auth_enforce': True, 'service_token': SERVICE_TOKEN})
        self.patch.start()
        return self

    def __exit__(self, *exc):
        self.patch.stop()
        patch.stopall()


def stream(path, headers):
    return Stream(path, list(headers.items())).open()


@contextlib.contextmanager
def derived(ids):
    """The house's placements, as the stream route derives them, stood in by a fixed set.
    The route reads them once its response has started, so the stand-in stays until the
    test's People() context ends (patch.stopall there)."""
    import main
    patch.object(main, '_house_stream_entities', lambda area=None: set(ids)).start()
    yield


# ---------------------------------------------------------------- tests

def test_state_changed_reaches_a_subscriber_within_a_second():
    with fake_ha() as hub, People() as who:
        started(hub)
        q = _events().subscribe(['light.kitchen'])
        with derived(['light.kitchen']):
            s = stream(STREAM, who.panel)
        try:
            check(s.status == 200, f'the panel reads the stream: {s.status} {s.text()[:200]}')
            check(s.media.startswith('text/event-stream'), f'an SSE stream: {s.media!r}')
            time.sleep(0.3)     # the route's own subscription settles
            t0 = time.monotonic()
            hub.push('light.kitchen', 'on', brightness=200, color_mode='brightness')
            item = q.get(timeout=1.0)
            check(time.monotonic() - t0 < 1.0, 'the queue hears it within a second')
            check(item['entity_id'] == 'light.kitchen', item)
            check(item['state']['state'] == 'on' and item['state']['attributes'].get('brightness') == 200,
                  f'the new state, attributes and all: {item}')
            hit = lambda: [c for c in s.changes() if c.get('entity_id') == 'light.kitchen'
                           and (c.get('state') or {}).get('state') == 'on']
            check(wait_until(lambda: bool(hit()), 1.0 - (time.monotonic() - t0)),
                  f'the SSE stream carries it within a second of HA: {s.text()[:400]!r}')
            change = hit()[0]
            check(change['state']['attributes'].get('brightness') == 200, change)
            check(not s.ended, 'the stream stays open')
        finally:
            _events().unsubscribe(q)
            check(s.close(), 'the stream ends when the browser goes away')


def test_filter_by_entities():
    with fake_ha() as hub, People() as who:
        started(hub)
        only = _events().subscribe(['light.kitchen', 'lock.back'])
        every = _events().subscribe()
        # A list in the URL is ignored: the page's set is the server's (C11).
        with derived(['light.kitchen', 'lock.back']):
            s = stream(STREAM + '?entities=switch.other', who.panel)
        try:
            time.sleep(0.3)
            hub.push('switch.other', 'on')
            hub.push('light.kitchen', 'on')
            hub.push('lock.back', 'unlocked')
            hub.push('switch.other', 'off')
            want = {('light.kitchen', 'on'), ('lock.back', 'unlocked')}
            seen = lambda: {(c['entity_id'], (c.get('state') or {}).get('state')) for c in s.changes()}
            check(wait_until(lambda: want <= seen(), 2), f'both asked-for changes arrive: {s.text()[:400]!r}')
            time.sleep(0.2)
            ids = {c['entity_id'] for c in s.changes()}
            check(ids <= {'light.kitchen', 'lock.back'}, f'nothing the page did not ask for: {sorted(ids)}')
            got = []
            while True:
                try:
                    got.append(only.get(timeout=0.5))
                except queue.Empty:
                    break
            check([(g['entity_id'], g['state']['state']) for g in got] == [('light.kitchen', 'on'), ('lock.back', 'unlocked')],
                  f'subscribe(entities) hears only those, in order: {got}')
            got = []
            while True:
                try:
                    got.append(every.get(timeout=0.5))
                except queue.Empty:
                    break
            check([g['entity_id'] for g in got] == ['switch.other', 'light.kitchen', 'lock.back', 'switch.other'],
                  f'subscribe() with no filter hears every change: {[g["entity_id"] for g in got]}')
        finally:
            _events().unsubscribe(only)
            _events().unsubscribe(every)
            check(s.close(), 'the stream ends when the browser goes away')


def test_no_ha_no_errors():
    ev = _events()
    tried = []
    real_connect = ev._connect
    ev._connect = lambda *a, **k: tried.append(a) or (_ for _ in ()).throw(AssertionError('connected with no HA'))
    out, logs = io.StringIO(), LogWatch()
    try:
        with People() as who, contextlib.redirect_stdout(out), logs:
            check(ha_api._ws_url_and_token() == (None, None), 'this test runs with no Home Assistant configured')
            before = {t.ident for t in threading.enumerate()}
            check(ev.start() in (None, False), 'start() with no HA reports that it did not start')
            ev.start()
            time.sleep(0.3)
            spawned = [t.name for t in threading.enumerate() if t.ident not in before and t.is_alive()]
            check(not spawned, f'no thread starts with no Home Assistant: {spawned}')
            q = ev.subscribe(['light.kitchen'])
            s = stream(STREAM, who.panel)
            try:
                check(s.status == 200 and s.media.startswith('text/event-stream'),
                      f'the stream still answers with no HA: {s.status} {s.media!r} {s.text()[:200]!r}')
                time.sleep(1.5)
                check(not s.changes(), f'and stays quiet: {s.text()[:300]!r}')
                check(not s.ended, 'it neither ends nor errors')
                check(q.empty(), 'a subscriber hears nothing')
            finally:
                ev.unsubscribe(q)
                check(s.close(), 'the stream ends when the browser goes away')
            ev.stop()
            ev.stop()
        check(not tried, f'nothing tried to connect: {tried}')
        printed = out.getvalue()
        complaints = [line for line in printed.splitlines() if 'Traceback' in line
                      or ('ha_events' in line or '[ha_api]' in line) and ('fail' in line.lower() or 'error' in line.lower())]
        check(not complaints, f'nothing complains with no HA: {complaints[:5]}')
        check(not logs.records, f'nothing logged an error: {[r.getMessage() for r in logs.records]}')
    finally:
        ev._connect = real_connect


def test_reconnects_with_backoff():
    with fake_ha() as hub, People() as who:
        started(hub)
        q = _events().subscribe(['light.kitchen'])
        with derived(['light.kitchen']):
            s = stream(STREAM, who.panel)
        try:
            time.sleep(0.3)
            hub.push('light.kitchen', 'on')
            check(q.get(timeout=1)['state']['state'] == 'on', 'live before the drop')
            # Home Assistant restarts: the connection dies and connects are refused for a while.
            hub.drop()
            refused = lambda: [t for t, ok in hub.attempts if not ok]
            check(wait_until(lambda: len(refused()) >= 4, 6),
                  f'the client keeps trying: {len(refused())} refused attempts')
            times = refused()[:4]
            gaps = [b - a for a, b in zip(times, times[1:])]
            check(gaps[0] >= 0.05, f'it waits between attempts, never spins: gaps {gaps}')
            check(gaps[2] >= 2 * gaps[0] and gaps[1] >= gaps[0] * 0.9 and gaps[2] >= gaps[1] * 0.9,
                  f'the wait grows: gaps {[round(g, 3) for g in gaps]}')
            check(not s.ended, 'the SSE client keeps its connection through the drop')
            # HA is back.
            n = sum(1 for c in hub.conns if c.sub_id is not None)
            hub.refuse = False
            check(wait_until(lambda: hub.subscribed(n + 1), 3),
                  f'the client reconnects and subscribes again: attempts {len(hub.attempts)}')
            time.sleep(0.1)
            t0 = time.monotonic()
            hub.push('light.kitchen', 'off')
            heard = []
            while time.monotonic() - t0 < 1.0 and not any(h['state']['state'] == 'off' for h in heard):
                try:
                    heard.append(q.get(timeout=max(0.01, 1.0 - (time.monotonic() - t0))))
                except queue.Empty:
                    break
            check(any(h['entity_id'] == 'light.kitchen' and h['state']['state'] == 'off' for h in heard),
                  f'the same subscriber hears state again within a second: {heard}')
            check(wait_until(lambda: any((c.get('state') or {}).get('state') == 'off' for c in s.changes()),
                             1.0 - (time.monotonic() - t0)),
                  f'the same SSE stream carries state again: {s.text()[-300:]!r}')
            check(not s.ended, 'still open')
        finally:
            _events().unsubscribe(q)
            check(s.close(), 'the stream ends when the browser goes away')


def test_stream_route_auth_tiers():
    check(auth.resolve('GET', STREAM) == auth.WALL_OR_SERVICE,
          f'the stream is WALL_OR_SERVICE: {auth.resolve("GET", STREAM)}')
    with fake_ha() as hub, People() as who:
        started(hub)
        cases = (
            ('a wall panel', STREAM, who.panel, 200),
            ('the service', STREAM, who.service, 200),
            # EventSource cannot set headers: a person's token rides the query.
            ('a parent by query token', STREAM + '?member_token=' + who.mum_token, {}, 200),
            ('anonymous off the LAN', STREAM, {'CF-Connecting-IP': '203.0.113.9'}, 401),
            ('a forged device token off the LAN', STREAM,
             {'CF-Connecting-IP': '203.0.113.9', 'X-Device-Token': 'not-a-token'}, 401),
        )
        for name, path, headers, want in cases:
            with derived(['light.kitchen']):
                s = stream(path, headers)
            try:
                check(s.status == want, f'{name}: {s.status} (want {want}) {s.text()[:200]!r}')
                if want == 200:
                    check(s.media.startswith('text/event-stream'), f'{name}: {s.media!r}')
                else:
                    check(wait_until(lambda: s.ended, 2), f'{name}: the refusal ends the response')
                    check('data:' not in s.text(), f'{name}: a refusal carries no state: {s.text()[:200]!r}')
            finally:
                check(s.close(), f'{name}: the response ends')


def test_the_state_cache_is_warmed():
    with fake_ha() as hub:
        rows = ha_api.get_states()
        check(len(rows) == 3 and len(hub.rest_calls) == 1, f'the cache primed by one REST read: {hub.rest_calls}')
        started(hub)
        q = _events().subscribe()
        try:
            time.sleep(0.3)
            # The cache has gone stale by the clock: only the push can make it fresh again.
            with ha_api._cache_lock:
                ha_api._states_cache['ts'] = time.time() - 3600
            calls = len(hub.rest_calls)
            hub.push('light.kitchen', 'on', brightness=150)
            check(q.get(timeout=1)['entity_id'] == 'light.kitchen', 'pushed')
            time.sleep(0.1)
            rows = {r['entity_id']: r for r in ha_api.get_states()}
            check(len(hub.rest_calls) == calls,
                  f'get_states answered without a REST call after the push: {hub.rest_calls[calls:]}')
            check(rows.get('light.kitchen', {}).get('state') == 'on'
                  and rows['light.kitchen']['attributes'].get('brightness') == 150,
                  f'and it has the pushed state: {rows.get("light.kitchen")}')
            check(rows.get('lock.back', {}).get('state') == 'locked' and 'switch.other' in rows,
                  f'every other row is kept: {sorted(rows)}')
            check(ha_api.get_state('light.kitchen')['state'] == 'on', 'get_state reads the warm cache too')
            check(len(hub.rest_calls) == calls, f'still no REST call: {hub.rest_calls[calls:]}')
        finally:
            _events().unsubscribe(q)


def _house(areas=('kitchen', 'garage')):
    """A twin with a Kitchen room, and Home Assistant's devices: one in each area, one in none."""
    model = {'buildings': [{'id': 'b', 'rooms': [{'id': 'r', 'level': 'L1', 'ha_area': 'Kitchen'}]}]}
    catalogue = {'available': True,
                 'areas': [{'area_id': a, 'name': a.title()} for a in areas],
                 'devices': [
                     {'device_id': 'd-light', 'entity_id': 'light.kitchen', 'entities': ['light.kitchen', 'sensor.kitchen_power'],
                      'area_id': 'kitchen', 'kind': 'light', 'name': 'Kitchen light'},
                     {'device_id': 'd-lock', 'entity_id': 'lock.back', 'entities': ['lock.back'],
                      'area_id': 'garage', 'kind': 'lock', 'name': 'Back door'},
                     {'device_id': 'd-switch', 'entity_id': 'switch.other', 'entities': ['switch.other'],
                      'area_id': None, 'kind': 'switch', 'name': 'Somewhere'},
                 ]}
    return model, catalogue


def test_stream_set_is_derived_from_the_house():
    import main
    with fake_ha() as hub, People() as who, patch.object(main, '_house_ha_context', lambda settings=None: _house()):
        got = main._house_stream_entities()
        check(got == {'light.kitchen', 'lock.back'},
              f'every device in an area, and each room\'s lights, never one in no area: {sorted(got)}')
        check(main._house_stream_entities('kitchen') == {'light.kitchen'},
              f'a page narrows it by area: {sorted(main._house_stream_entities("kitchen"))}')
        started(hub)
        long = ','.join(f'light.l{i}' for i in range(800))
        s = stream(STREAM + '?entities=' + long, who.panel)
        n = stream(STREAM + '?area=kitchen', who.panel)
        try:
            check(s.status == 200 and n.status == 200, f'the stream opens: {s.status} {n.status}')
            time.sleep(0.3)
            for eid, st in (('switch.other', 'on'), ('light.kitchen', 'on'), ('lock.back', 'unlocked')):
                hub.push(eid, st)
            pairs = lambda x: {(c['entity_id'], (c.get('state') or {}).get('state')) for c in x.changes()}
            check(wait_until(lambda: {('light.kitchen', 'on'), ('lock.back', 'unlocked')} <= pairs(s), 2),
                  f'the house stream carries the house: {s.text()[:300]!r}')
            check(wait_until(lambda: ('light.kitchen', 'on') in pairs(n), 2), f'the kitchen stream: {n.text()[:300]!r}')
            time.sleep(0.2)
            check({c['entity_id'] for c in s.changes()} <= {'light.kitchen', 'lock.back'},
                  f'nothing outside the house, whatever the URL asked: {pairs(s)}')
            check({c['entity_id'] for c in n.changes()} == {'light.kitchen'}, f'the kitchen only: {pairs(n)}')
        finally:
            check(s.close() and n.close(), 'the streams end')
    with fake_ha(), patch.object(main, '_house_ha_context', lambda settings=None: ({'buildings': []}, {'available': False, 'areas': [], 'devices': []})):
        check(main._house_stream_entities() == set(), 'no Home Assistant catalogue: an empty set, no error')


def test_camera_tokens_never_reach_a_subscriber():
    with fake_ha() as hub, People() as who:
        started(hub)
        q = _events().subscribe(['camera.porch'])
        with derived(['camera.porch']):
            s = stream(STREAM, who.panel)
        try:
            time.sleep(0.3)
            hub.push('camera.porch', 'idle', access_token='cafe5eed', supported_features=0,
                     entity_picture='/api/camera_proxy/camera.porch?token=cafe5eed&width=640')
            item = q.get(timeout=1)
            attrs = item['state']['attributes']
            check('access_token' not in attrs, f'no access_token for a subscriber: {item}')
            check(attrs.get('entity_picture') == '/api/camera_proxy/camera.porch?width=640',
                  f'entity_picture keeps its path and other parameters, never the token: {attrs.get("entity_picture")}')
            check(wait_until(lambda: any(c['entity_id'] == 'camera.porch' for c in s.changes()), 1), 'the stream carries it')
            check('cafe5eed' not in s.text(), f'and never the token: {s.text()[:300]!r}')
            row = ha_api.get_state('camera.porch')
            check(row and row['attributes'].get('access_token') == 'cafe5eed', f'the server\'s own cache keeps it: {row}')
            hub.push('light.kitchen', 'on', brightness=10, entity_picture='/local/x.png?token=keep')
            item = q.get(timeout=0.2) if not q.empty() else None
            check(item is None, 'only the camera was asked for')
        finally:
            _events().unsubscribe(q)
            check(s.close(), 'the stream ends')


def test_a_push_replaces_its_row_in_place():
    with fake_ha() as hub:
        rows = ha_api.get_states()
        started(hub)
        time.sleep(0.3)
        with ha_api._cache_lock:
            cache = ha_api._states_cache['data']
            count = len(cache)
        q = _events().subscribe(['light.kitchen'])
        try:
            for level in range(5):
                hub.push('light.kitchen', 'on', brightness=level)
                q.get(timeout=1)
            with ha_api._cache_lock:
                now = ha_api._states_cache['data']
            check(now is cache, 'a push changes the cached list in place: no whole-house copy per change')
            check(len(now) == count and [r['entity_id'] for r in now].count('light.kitchen') == 1,
                  f'one row per entity: {[r["entity_id"] for r in now]}')
            check(ha_api.get_state('light.kitchen')['attributes'].get('brightness') == 4, 'holding the newest state')
            hub.push('switch.new', 'on')
            time.sleep(0.2)
            check(ha_api.get_state('switch.new')['state'] == 'on', 'a new entity is added')
        finally:
            _events().unsubscribe(q)


class WarnWatch(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records = []

    def emit(self, record):
        if record.levelno == logging.WARNING:
            self.records.append(record)


def test_a_failing_connection_says_why_once_per_reason():
    watch = WarnWatch()
    logging.getLogger().addHandler(watch)
    try:
        with fake_ha() as hub:
            hub.token = 'a-different-token'      # HA refuses the token the server holds
            _events().start()
            check(wait_until(lambda: len(hub.attempts) >= 4, 6), f'it keeps trying: {len(hub.attempts)}')
            refused = [r.getMessage() for r in watch.records]
            check(len(refused) == 1, f'one warning for a refused token, not one per attempt: {refused}')
            check('auth' in refused[0].lower() or 'token' in refused[0].lower(), f'naming the reason: {refused}')
            check(TOKEN not in refused[0], 'without the token itself')
            hub.refuse = True                    # now Home Assistant is away altogether
            n = len(hub.attempts)
            check(wait_until(lambda: len(hub.attempts) >= n + 3, 6), 'it keeps trying')
            check(len(watch.records) == 2, f'a new reason is said once more: {[r.getMessage() for r in watch.records]}')
            hub.refuse = False
            hub.token = TOKEN
            check(wait_until(lambda: hub.subscribed(1), 6), 'and recovers')
            hub.drop()
            hub.refuse = False
            check(wait_until(lambda: hub.subscribed(2), 6), 'and recovers again')
            check(len(watch.records) == 3, f'after recovering, a failure is news again: {[r.getMessage() for r in watch.records]}')
    finally:
        logging.getLogger().removeHandler(watch)


def test_saving_home_assistant_settings_starts_the_stream():
    import main
    calls = []
    with People() as who, patch.object(_events(), 'restart', lambda: calls.append('restart')), \
            patch.object(main, 'trigger_background_refresh', lambda: None), \
            patch.object(storage, 'update_settings', lambda data: None):
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        headers = {'X-Member-Token': who.mum_token}
        r = client.post('/api/settings', json={'ha_base_url': 'http://ha.test:8123', 'ha_token': 'new-token'}, headers=headers)
        check(r.status_code == 200, f'a parent saves Home Assistant\'s address: {r.status_code} {r.text[:200]}')
        check(calls == ['restart'], f'the state stream (re)starts at once, no restart of the app needed: {calls}')
        r = client.post('/api/settings', json={'timezone': 'America/Chicago'}, headers=headers)
        check(r.status_code == 200 and calls == ['restart'], f'an unrelated save leaves it alone: {calls}')


def test_the_stream_waits_without_polling():
    sleeps = []
    real = asyncio.sleep

    async def counted(delay, *a, **k):
        sleeps.append(delay)
        return await real(delay, *a, **k)
    with fake_ha() as hub, People() as who:
        started(hub)
        with derived(['light.kitchen']):
            s = stream(STREAM, who.panel)
        try:
            time.sleep(0.2)
            with patch.object(asyncio, 'sleep', counted):
                time.sleep(1.0)
                t0 = time.monotonic()
                hub.push('light.kitchen', 'on')
                check(wait_until(lambda: any(c['entity_id'] == 'light.kitchen' for c in s.changes()), 1),
                      'a change is carried at once')
                took = time.monotonic() - t0
            check(len(sleeps) <= 2, f'an idle stream does not wake ten times a second: {len(sleeps)} sleeps in ~1 s')
            check(took < 0.5, f'and a change wakes it: {took:.3f} s')
        finally:
            check(s.close(), 'the stream ends')


class LogWatch(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def __enter__(self):
        logging.getLogger().addHandler(self)
        return self

    def __exit__(self, *exc):
        logging.getLogger().removeHandler(self)


TESTS = [
    test_state_changed_reaches_a_subscriber_within_a_second,
    test_filter_by_entities,
    test_no_ha_no_errors,
    test_reconnects_with_backoff,
    test_stream_route_auth_tiers,
    test_the_state_cache_is_warmed,
    test_stream_set_is_derived_from_the_house,
    test_camera_tokens_never_reach_a_subscriber,
    test_a_push_replaces_its_row_in_place,
    test_a_failing_connection_says_why_once_per_reason,
    test_saving_home_assistant_settings_starts_the_stream,
    test_the_stream_waits_without_polling,
]


def main():
    passed = 0
    for test in TESTS:
        try:
            test()
            passed += 1
            print(f'  ok   {test.__name__}')
        except Exception as e:
            print(f'  FAIL {test.__name__}: {type(e).__name__}: {str(e)[:600]}')
            if not isinstance(e, AssertionError):
                traceback.print_exc(limit=3)
    print(f'{passed}/{len(TESTS)} passed')
    return passed == len(TESTS)


if __name__ == '__main__':
    ok = main()
    sys.stdout.flush()
    os._exit(0 if ok else 1)
