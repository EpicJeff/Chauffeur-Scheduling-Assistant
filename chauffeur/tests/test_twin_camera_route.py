"""The house's camera still, through the server (Task 5 of
docs/superpowers/plans/2026-11-11-twin-device-controls.md; brief
.superpowers/sdd/2026-11-11-twin-device-controls/task-5-brief.md; spec
docs/superpowers/specs/2026-11-11-twin-device-controls-design.md decision 3, Camera;
plan Global Constraints, Camera).

The route: GET /api/house/camera/{entity_id} (WALL_OR_SERVICE). The server fetches
Home Assistant's /api/camera_proxy/<entity_id> with its own token and answers the
image; the token never reaches the page. It obeys the household grid: a caller the
grid refuses the camera's kind outright (for a camera that kind is 'other') gets 403
and Home Assistant is never asked. Plain answers when there is nothing to show:
- Home Assistant configured but unreachable: 503, a short plain message;
- no Home Assistant configured, an unknown camera, or an entity that is not a
  camera: 404 (400 is accepted for an entity id that is not a camera's), a short
  plain message, and no error logged.

Home Assistant is faked at the HTTP layer, below services/ha_api: requests.request
(ha_api._request: /api/states, /api/states/<id>, /api/config) and requests.get
(ha_api.fetch_binary and stream_binary: /api/camera_proxy/<id>). It answers the
camera only with the server's own token (Authorization: Bearer <token>), and records
every request. The server finds Home Assistant through settings ha_base_url and
ha_token (HA_BASE_URL, HA_TOKEN and SUPERVISOR_TOKEN are cleared for the run).

Not pinned here: what a caller the grid would offer the camera only after
identification (an 'ask' cell) sees.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_camera_route.py
"""
import logging
import os
import sys
import tempfile
import traceback
from unittest.mock import patch

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_camera_route_')
for _name in ('HA_BASE_URL', 'HA_TOKEN', 'SUPERVISOR_TOKEN'):
    os.environ.pop(_name, None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import requests  # noqa: E402

from services import auth, control_rules as cr, ha_api, storage  # noqa: E402

_real_settings = storage.get_settings

ROUTE = '/api/house/camera/{entity_id}'
HA_BASE = 'http://ha.test:8123'
HA_SECRET = 'ha-long-lived-token-SECRET-7f3a9c'
SERVICE_TOKEN = 'svc-camera-route-token'
FRAME = b'\xff\xd8\xff\xe0' + b'porch-frame-' * 16 + b'\xff\xd9'
OFF_LAN = {'CF-Connecting-IP': '203.0.113.9'}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def path(entity_id):
    return ROUTE.replace('{entity_id}', entity_id)


# ---------------------------------------------------------------- Home Assistant over HTTP

class Resp:
    def __init__(self, status, body=None, content=None, content_type='application/json'):
        import json as _json
        self.status_code = status
        self._body = body
        self.content = content if content is not None else (_json.dumps(body).encode() if body is not None else b'')
        self.text = self.content.decode('latin-1') if body is not None or content is None else ''
        self.headers = {'Content-Type': content_type}

    def json(self):
        return self._body

    def iter_content(self, chunk_size=1024):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def close(self):
        pass

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def _state(eid, st, **attrs):
    return {'entity_id': eid, 'state': st, 'attributes': {'friendly_name': eid.split('.', 1)[1].replace('_', ' ').title(), **attrs}}


class FakeHttpHA:
    def __init__(self):
        self.up = True
        self.calls = []          # (method, url, headers)
        self.kwargs = []         # the keyword arguments of each camera fetch (stream, timeout)
        self.frame = FRAME
        self.states = [
            _state('camera.porch', 'idle', entity_picture='/api/camera_proxy/camera.porch?token=cafe5eed',
                   access_token='cafe5eed', supported_features=0),
            _state('light.kitchen', 'off'),
        ]

    def state_reads(self):
        return [c for c in self.calls if c[1].split('?')[0] == f'{HA_BASE}/api/states']

    def camera_fetches(self, entity_id=None):
        return [c for c in self.calls if c[0] == 'GET' and '/api/camera_proxy' in c[1]
                and (entity_id is None or c[1].split('?')[0].endswith('/' + entity_id))]

    def _answer(self, method, url, headers):
        self.calls.append((method, url, dict(headers or {})))
        if not self.up:
            raise requests.ConnectionError('Home Assistant is down (fake)')
        if not url.startswith(HA_BASE):
            return Resp(404, {'message': 'not this host'})
        if (headers or {}).get('Authorization') != f'Bearer {HA_SECRET}':
            return Resp(401, {'message': 'unauthorized'})
        route = url[len(HA_BASE):].split('?')[0]
        if route == '/api/config':
            return Resp(200, {'version': '2026.11.0'})
        if route == '/api/states':
            return Resp(200, self.states)
        if route.startswith('/api/states/'):
            row = next((s for s in self.states if s['entity_id'] == route.rsplit('/', 1)[1]), None)
            return Resp(200, row) if row else Resp(404, {'message': 'Entity not found.'})
        if route.startswith(('/api/camera_proxy/', '/api/camera_proxy_stream/')):
            eid = route.rsplit('/', 1)[1]
            if any(s['entity_id'] == eid for s in self.states) and eid.startswith('camera.'):
                return Resp(200, content=self.frame, content_type='image/jpeg')
            return Resp(404, {'message': 'Entity not found.'})
        return Resp(404, {'message': 'not found'})

    def request(self, method, url, headers=None, **kw):
        return self._answer(method.upper(), url, headers)

    def get(self, url, headers=None, **kw):
        if '/api/camera_proxy' in url:
            self.kwargs.append(kw)
        return self._answer('GET', url, headers)


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


class Ctx:
    """Enforcement on; a parent, a wall panel, the service token; HA over fake HTTP."""

    def __init__(self, configured=True):
        self.ha = FakeHttpHA()
        self.configured = configured
        self.extra = {}

    def settings(self):
        out = {**_real_settings(), 'auth_enforce': True, 'service_token': SERVICE_TOKEN}
        if self.configured:
            out.update(ha_base_url=HA_BASE, ha_token=HA_SECRET)
        else:
            out.update(ha_base_url='', ha_token='')
        out.update(self.extra)
        return out

    def __enter__(self):
        from fastapi.testclient import TestClient
        import main
        if not storage.get_member('mum'):
            storage.add_member({'id': 'mum', 'name': 'Mum', 'role': 'parent', 'status': 'active'})
        self.mum = {'X-Member-Token': storage.create_member_token('mum', proof='password', minted_on='personal')}
        self.panel = {'X-Device-Token': storage.enrol_device_token('panel-cam', 'Kitchen panel', by_member='mum')}
        self.service = {'X-Service-Token': SERVICE_TOKEN}
        self.patches = [patch.object(storage, 'get_settings', side_effect=self.settings),
                        patch.object(requests, 'request', self.ha.request),
                        patch.object(requests, 'get', self.ha.get)]
        for p in self.patches:
            p.start()
        ha_api._states_cache.update(ts=0.0, data=None, failed=False)
        self.client = TestClient(main.app)
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        ha_api._states_cache.update(ts=0.0, data=None, failed=False)

    def get(self, entity_id, headers):
        return self.client.get(path(entity_id), headers=headers)


def _plain(r, status):
    """A refusal a person can read: the status, a short message, nothing of the server's insides."""
    check(r.status_code == status, f'{status} expected: {r.status_code} {r.text[:300]!r}')
    body = r.text
    check(len(body) < 400, f'a short answer: {body[:400]!r}')
    if r.headers.get('content-type', '').startswith('application/json'):
        detail = r.json().get('detail')
        check(isinstance(detail, str) and detail.strip(), f'a plain message: {r.json()!r}')
    for leak in (HA_SECRET, HA_BASE, 'ha.test', 'Traceback', 'camera_proxy'):
        check(leak not in body and leak not in str(r.headers), f'the answer names {leak!r}: {body!r} {dict(r.headers)!r}')


# ---------------------------------------------------------------- tests

def test_camera_route_auth_tier():
    check(auth.resolve('GET', ROUTE) == auth.WALL_OR_SERVICE, f'the camera route is WALL_OR_SERVICE: {auth.resolve("GET", ROUTE)}')
    with Ctx() as c:
        for name, headers in (('a wall panel', c.panel), ('the service', c.service), ('a parent', c.mum)):
            r = c.get('camera.porch', headers)
            check(r.status_code == 200 and r.content == FRAME, f'{name}: {r.status_code} {r.text[:200]!r}')
        fetched = len(c.ha.camera_fetches())
        r = c.get('camera.porch', OFF_LAN)
        check(r.status_code == 401, f'anonymous off the LAN: {r.status_code}')
        r = c.get('camera.porch', {**OFF_LAN, 'X-Device-Token': 'not-a-token'})
        check(r.status_code == 401, f'a forged device token off the LAN: {r.status_code}')
        check(len(c.ha.camera_fetches()) == fetched, 'a refused caller never reaches Home Assistant')


def test_camera_still_through_the_server_no_token_on_page():
    with Ctx() as c:
        r = c.get('camera.porch', c.panel)
        check(r.status_code == 200, f'the panel gets the still: {r.status_code} {r.text[:300]!r}')
        check(r.content == FRAME, 'the bytes are Home Assistant\'s frame')
        check(r.headers.get('content-type', '').startswith('image/jpeg'), f'served as the image it is: {r.headers.get("content-type")}')
        fetched = c.ha.camera_fetches('camera.porch')
        check(len(fetched) == 1, f'one camera_proxy fetch per still: {fetched}')
        method, url, headers = fetched[0]
        check(url.split('?')[0] == f'{HA_BASE}/api/camera_proxy/camera.porch', f'HA\'s camera_proxy: {url}')
        check(headers.get('Authorization') == f'Bearer {HA_SECRET}', f'with the server\'s own token: {headers}')
        check(HA_SECRET.encode() not in r.content and HA_SECRET not in str(r.headers), 'the still never carries the token')
        # The pages that draw the camera never carry the token either.
        for page in ('/house/twin', '/api/house/live'):
            got = c.client.get(page, headers=c.panel)
            check(got.status_code == 200, f'{page}: {got.status_code}')
            check(HA_SECRET not in got.text, f'{page} carries Home Assistant\'s token')
        # Home Assistant unreachable: a plain 503, with the camera remembered and with nothing cached.
        c.ha.up = False
        _plain(c.get('camera.porch', c.panel), 503)
        ha_api._states_cache.update(ts=0.0, data=None, failed=False)
        _plain(c.get('camera.porch', c.panel), 503)
        c.ha.up = True
        r = c.get('camera.porch', c.panel)
        check(r.status_code == 200 and r.content == FRAME, f'back when Home Assistant is: {r.status_code}')


def test_camera_obeys_the_grid():
    with Ctx() as c:
        rules = cr.default_rules({})
        rules['places']['panel']['other'] = 'no'
        c.extra = {'ha_control': rules}
        before = len(c.ha.camera_fetches())
        r = c.get('camera.porch', c.panel)
        check(r.status_code == 403, f'a panel the grid refuses cameras gets 403: {r.status_code} {r.text[:200]!r}')
        check(len(c.ha.camera_fetches()) == before, 'and Home Assistant is never asked for the frame')
        check(HA_SECRET not in r.text, 'the refusal carries no token')
        r = c.get('camera.porch', c.mum)
        check(r.status_code == 200 and r.content == FRAME, f'a parent the grid allows sees it: {r.status_code}')
        c.extra = {}
        r = c.get('camera.porch', c.panel)
        check(r.status_code == 200 and r.content == FRAME, f'the default grid shows the panel its camera: {r.status_code}')


def test_no_ha_camera_404s_plainly():
    with Ctx() as c, LogWatch() as log:
        r = c.get('camera.porch', c.panel)
        check(r.status_code == 200 and r.content == FRAME,
              f'fixture: the route serves a camera Home Assistant has (so a 404 below is the camera route answering): {r.status_code}')
        _plain(c.get('camera.nope', c.panel), 404)
        for eid in ('light.kitchen', 'sensor.camera_porch'):
            r = c.get(eid, c.panel)
            check(r.status_code in (400, 404), f'{eid} is not a camera: {r.status_code} {r.text[:200]!r}')
            _plain(r, r.status_code)
            check(not c.ha.camera_fetches(eid), f'{eid}: Home Assistant is never asked for a frame of it')
        check(not log.records, f'nothing logged as an error: {[x.getMessage() for x in log.records]}')
    with Ctx(configured=False) as c, LogWatch() as log:
        _plain(c.get('camera.porch', c.panel), 404)
        check(c.ha.calls == [], f'with no Home Assistant nothing is asked of one: {c.ha.calls}')
        check(not log.records, f'nothing logged as an error: {[x.getMessage() for x in log.records]}')


# ---------------------------------------------------------------- the grid on every camera lane (C9)

LEGACY = ('/api/camera_proxy/camera.porch', '/api/camera_proxy_stream/camera.porch')


def _kid():
    if not storage.get_member('kid'):
        storage.add_member({'id': 'kid', 'name': 'Kid', 'role': 'child', 'status': 'active'})
    return storage.create_member_token('kid', proof='password', minted_on='personal')


def _board_tile_url():
    """The board's camera tile, built by the board itself: the URL its img fetches."""
    from services import home_board
    data = home_board._tile_ha_image(None, config={'entity': 'camera.porch'})
    check(isinstance(data, dict) and data.get('url'), f'the board builds a camera tile: {data!r}')
    check('cafe5eed' not in str(data), f'the tile carries no camera token: {data!r}')
    return '/' + data['url']


def _image_path():
    return '/api/ha/image?path=' + requests.utils.quote('/api/camera_proxy/camera.porch', safe='')


def test_legacy_camera_proxies_obey_the_grid():
    with Ctx() as c:
        kid = _kid()
        rules = cr.default_rules({})
        rules['people']['child']['other'] = 'no'
        c.extra = {'ha_control': rules}
        lanes = (*LEGACY, _board_tile_url(), _image_path())
        before = len(c.ha.camera_fetches())
        for route in lanes:
            for how, headers, query in (('header', {'X-Member-Token': kid}, ''),
                                        ('query', {}, ('&' if '?' in route else '?') + 'member_token=' + kid)):
                r = c.client.get(route + query, headers=headers)
                check(r.status_code == 403, f'a kid the grid refuses cameras ({how} token): {route} -> {r.status_code} {r.text[:200]!r}')
                check('cafe5eed' not in r.text and HA_SECRET not in r.text, f'{route}: the refusal carries no token')
        check(len(c.ha.camera_fetches()) == before, f'Home Assistant is never asked for a refused frame: {c.ha.camera_fetches()[before:]}')
        # A panel the grid refuses cameras: the same on every lane.
        rules = cr.default_rules({})
        rules['places']['panel']['other'] = 'no'
        c.extra = {'ha_control': rules}
        for route in lanes:
            r = c.client.get(route, headers=c.panel)
            check(r.status_code == 403, f'a panel the grid refuses cameras: {route} -> {r.status_code}')
        check(len(c.ha.camera_fetches()) == before, 'and Home Assistant is never asked')


def test_allowed_callers_still_see_every_camera_lane():
    with Ctx() as c:
        kid = _kid()
        lanes = (*LEGACY, _board_tile_url(), _image_path())
        for name, headers in (('a wall panel', c.panel), ('a parent', c.mum),
                              ('a kid the default grid allows', {'X-Member-Token': kid})):
            for route in lanes:
                r = c.client.get(route, headers=headers)
                check(r.status_code == 200 and r.content == FRAME, f'{name}: {route} -> {r.status_code} {r.text[:200]!r}')
        # A hosted camera element builds ?token=<access_token>; with the token kept on the
        # server it sends "undefined", and still gets its frame (the server's bearer goes up).
        r = c.client.get(LEGACY[0] + '?token=undefined', headers=c.panel)
        check(r.status_code == 200 and r.content == FRAME, f'a hosted card with no camera token still gets its frame: {r.status_code}')


def test_control_switched_off_never_hides_cameras():
    """Ruling C12: the household switch governs CONTROL. Seeing a camera is not
    control, so a household that turns control off keeps every camera lane it had
    before the grid reached cameras (never drop what a person can do)."""
    with Ctx() as c:
        kid = _kid()
        rules = cr.default_rules({})
        rules['enabled'] = False
        c.extra = {'ha_control': rules}
        lanes = ('/api/house/camera/camera.porch', *LEGACY, _board_tile_url(), _image_path())
        for name, headers in (('a wall panel', c.panel), ('a parent', c.mum), ('a kid', {'X-Member-Token': kid})):
            for route in lanes:
                r = c.client.get(route, headers=headers)
                check(r.status_code == 200 and r.content == FRAME,
                      f'control off, {name}: {route} -> {r.status_code} {r.text[:200]!r}')


def test_camera_tokens_never_leave_the_server():
    from services import ha_cards
    with Ctx() as c:
        r = c.client.get('/api/ha/card/states?fresh=1', headers=c.panel)
        check(r.status_code == 200, f'card states: {r.status_code}')
        row = r.json()['states']['camera.porch']
        check('access_token' not in row['attributes'], f'no access_token in the states a page reads: {row}')
        check(row['attributes'].get('entity_picture') == '/api/camera_proxy/camera.porch',
              f'entity_picture keeps its path without the token: {row}')
        check('cafe5eed' not in r.text, 'the token appears nowhere in the answer')
        for name, payload in (('states_for', ha_cards.states_for(['camera.porch'])),
                              ('states_all', ha_cards.states_all(ttl=0)),
                              ('a picture-entity card', ha_cards.prepare('type: picture-entity\nentity: camera.porch'))):
            check('cafe5eed' not in repr(payload), f'{name} carries the camera token: {payload!r}'[:400])
        check(any((s.get('attributes') or {}).get('access_token') == 'cafe5eed' for s in ha_api._states_cache['data'] or []),
              'the server keeps the token in its own cache')


def test_a_still_reads_no_whole_house_and_is_bounded():
    with Ctx() as c:
        for _ in range(3):
            r = c.get('camera.porch', c.panel)
            check(r.status_code == 200 and r.content == FRAME, f'a still: {r.status_code}')
        check(len(c.ha.state_reads()) <= 1, f'three stills read the whole house at most once: {len(c.ha.state_reads())}')
        kw = c.ha.kwargs[-1]
        check(kw.get('stream') is True, f'the frame is read as a stream, so a cap can stop it: {kw}')
        timeout = kw.get('timeout')
        longest = max(timeout) if isinstance(timeout, (tuple, list)) else timeout
        check(longest is not None and longest <= 8, f'and with a timeout of at most 8 s: {kw}')
        c.ha.frame = b'\xff\xd8' + b'x' * (5 * 1024 * 1024)
        r = c.get('camera.porch', c.panel)
        check(r.status_code in (502, 503) and len(r.content) < 1000,
              f'an oversized frame is refused, never relayed: {r.status_code} {len(r.content)}')
        r = c.client.get(LEGACY[0], headers=c.panel)
        check(r.status_code in (502, 503) and len(r.content) < 1000,
              f'the hosted cards still is bounded too: {r.status_code} {len(r.content)}')


def test_refusal_copy_follows_what_the_grid_needs():
    with Ctx() as c:
        rules = cr.default_rules({})
        rules['places']['panel']['other'] = 'ask'
        c.extra = {'ha_control': rules}
        r = c.get('camera.porch', c.panel)
        check(r.status_code == 403 and 'phone' in r.json()['detail'], f'a panel that must identify is sent to a phone: {r.text}')
        rules = cr.default_rules({})
        rules['proof']['other'] = True
        c.extra = {'ha_control': rules}
        if not storage.get_member('dad'):
            storage.add_member({'id': 'dad', 'name': 'Dad', 'role': 'adult', 'status': 'active'})
        dad = {'X-Member-Token': storage.create_member_token('dad', proof='link', minted_on='personal')}
        r = c.get('camera.porch', dad)
        check(r.status_code == 403, f'a sign-in without proof is refused: {r.status_code} {r.text}')
        check('phone' not in r.json()['detail'].lower(),
              f'a person already on their own device is not sent to their phone: {r.text}')


def test_the_access_log_never_keeps_a_token():
    """EventSource cannot set headers, so the stream's token rides its URL, and the
    server's access log printed it on every reconnect (review L5). uvicorn's access
    lines are logged by 'uvicorn.access' with the path as an argument."""
    import main  # noqa: F401  (installs the filter)

    class Keep(logging.Handler):
        def __init__(self):
            super().__init__(level=logging.INFO)
            self.lines = []

        def emit(self, record):
            self.lines.append(record.getMessage())
    access = logging.getLogger('uvicorn.access')
    keep, level = Keep(), access.level
    access.addHandler(keep)
    access.setLevel(logging.INFO)
    try:
        for path in ('/api/ha/stream?device_token=PANELSECRET1', '/api/house/camera/camera.porch?t=1&member_token=MEMBERSECRET2',
                     '/api/camera_proxy/camera.porch?token=cafe5eed', '/api/x?service_token=SVCSECRET3&a=1'):
            access.info('%s - "%s %s HTTP/%s" %d', '192.168.1.40:5000', 'GET', path, '1.1', 200)
    finally:
        access.removeHandler(keep)
        access.setLevel(level)
    text = '\n'.join(keep.lines)
    check(len(keep.lines) == 4, f'every request is still logged: {keep.lines}')
    for secret in ('PANELSECRET1', 'MEMBERSECRET2', 'cafe5eed', 'SVCSECRET3'):
        check(secret not in text, f'the access log keeps {secret}: {text}')
    check('/api/ha/stream?device_token=' in text and '&a=1' in text, f'and the rest of each line: {text}')


TESTS = [v for k, v in sorted(globals().items()) if k.startswith('test_') and callable(v)]


if __name__ == '__main__':
    passed = 0
    for fn in TESTS:
        try:
            fn()
            passed += 1
            print(f'ok   {fn.__name__}')
        except Exception:
            print(f'FAIL {fn.__name__}')
            traceback.print_exc(limit=3)
    print(f'{passed}/{len(TESTS)} passed')
    sys.exit(0 if passed == len(TESTS) else 1)
