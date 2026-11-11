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
        self.states = [
            _state('camera.porch', 'idle', entity_picture='/api/camera_proxy/camera.porch?token=cafe5eed',
                   access_token='cafe5eed', supported_features=0),
            _state('light.kitchen', 'off'),
        ]

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
        if route.startswith('/api/camera_proxy/'):
            eid = route.rsplit('/', 1)[1]
            if any(s['entity_id'] == eid for s in self.states) and eid.startswith('camera.'):
                return Resp(200, content=FRAME, content_type='image/jpeg')
            return Resp(404, {'message': 'Entity not found.'})
        return Resp(404, {'message': 'not found'})

    def request(self, method, url, headers=None, **kw):
        return self._answer(method.upper(), url, headers)

    def get(self, url, headers=None, **kw):
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
