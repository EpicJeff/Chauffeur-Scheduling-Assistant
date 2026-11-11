"""Bake storage and keys (Task 2 of docs/superpowers/plans/2026-11-10-house-baked-lights.md;
spec docs/superpowers/specs/2026-11-10-house-baked-lights-design.md, decisions 4 and 5).

Real FastAPI app, auth enforcement ON and the local service grace OFF
(storage.get_settings patched), a parent (mum), a child (kid) and an enrolled
wall panel. Routes under test:

- POST /api/house/bakes/{key}/{page}.png   PARENTS          raw PNG body
- GET  /api/house/bakes/{key}/{page}.png   WALL_OR_SERVICE  ETag, 304, 404
- GET  /api/house/bakes/{key}              WALL_OR_SERVICE  the manifest, 404 when none
- PUT  /api/house/bakes/{key}              PARENTS          the manifest (JSON body)
- services.twin_bakes.prune(live_keys)     removes every other key's bakes

Decisions pinned here where the plan leaves room:

- Where pages live: os.path.join(twin_store.DATA_DIR, 'bakes', key, f'{page}.png')
  (twin_store.DATA_DIR is the house's data folder, <data>/twin). The manifest
  is a .json file beside the pages; nothing else is left in a key's folder
  (no temp files after a write, even under concurrent writes).
- Key format: lowercase hex, 16 to 64 characters (^[0-9a-f]{16,64}$). A bad key
  is refused with 400 on every write; reads answer 400 or 404; nothing is ever
  written for it. Page: a non-negative decimal integer; anything else is
  refused (400, 404 or 422).
- Upload body: raw bytes (not multipart), Content-Type image/png. It must start
  with the PNG signature (else 400 or 415). Any PNG size is accepted (the 2048
  page size is the client's business). Over 16 MiB (16 * 1024 * 1024 bytes):
  413, nothing stored.
- Upload answer: 200 with JSON {'etag': <the same value the GET's ETag header
  then carries>}.
- GET: 200, Content-Type image/png, the exact bytes, an ETag header; a matching
  If-None-Match answers 304; new bytes give a new ETag. A missing page is 404.
- Manifest: {'pages': int >= 1, 'lights': {device: {'page', 'channel', 'key'}},
  'sky': {'page', 'channel'}}. channel 0..3; page 0..pages-1; a light's key has
  the key format. A bad manifest is 400 and nothing is stored. GET answers the
  stored pages, lights and sky unchanged.
- Concurrency (Review Focus 2): while two parents upload different bytes to the
  same page and a panel reads it, every read is exactly one of the uploads (never
  a mix, never truncated, never an error) and every upload answers 200. The
  last write wins. On Windows a replace onto a file a reader holds open fails,
  so a read must not hold the file open across a replace (or the replace must
  wait and retry); on Linux the rename is atomic by itself.

The every-route-has-a-rule check lives in tests/test_auth.py; this file pins
the four rules' tiers directly.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_bakes.py
"""
import io
import os
import re
import sys
import tempfile
import threading
import traceback
from unittest.mock import patch

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_bakes_')
os.environ.pop('HA_BASE_URL', None)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PIL import Image  # noqa: E402

from services import auth, storage  # noqa: E402
from services import twin_store  # noqa: E402

_real_settings = storage.get_settings

PAGE_TEMPLATE = '/api/house/bakes/{key}/{page}.png'
MANIFEST_TEMPLATE = '/api/house/bakes/{key}'
CAP = 16 * 1024 * 1024
PNG_SIG = b'\x89PNG\r\n\x1a\n'
STORED = re.compile(r'^(\d+\.png|[^.][^/]*\.json)$')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def page_url(key, page):
    return f'/api/house/bakes/{key}/{page}.png'


def manifest_url(key):
    return f'/api/house/bakes/{key}'


def key_of(n):
    return f'{n:040x}'


def png(size=8, seed=0, noise=False):
    """A real RGBA PNG; noise=True makes it incompressible (big)."""
    if noise:
        data = os.urandom(size * size * 4)
    else:
        data = bytes((seed + i) % 256 for i in range(size * size * 4))
    out = io.BytesIO()
    Image.frombytes('RGBA', (size, size), data).save(out, format='PNG')
    return out.getvalue()


def bakes_dir():
    return os.path.join(twin_store.DATA_DIR, 'bakes')


def stored_path(key, page):
    return os.path.join(bakes_dir(), key, f'{page}.png')


def manifest(pages=2):
    return {'pages': pages,
            'lights': {'dev-k-light': {'page': 0, 'channel': 0, 'key': key_of(0xa1)},
                       'dev-k-lamp': {'page': 0, 'channel': 3, 'key': key_of(0xa2)},
                       'dev-hall': {'page': pages - 1, 'channel': 1, 'key': key_of(0xa3)}},
            'sky': {'page': pages - 1, 'channel': 2}}


class Ctx:
    """People, a panel and the client, auth enforced; enter with `with Ctx() as c`."""

    def __enter__(self):
        from fastapi.testclient import TestClient
        import main
        for mid, role in (('mum', 'parent'), ('kid', 'child')):
            if not storage.get_member(mid):
                storage.add_member({'id': mid, 'name': mid.title(), 'role': role, 'status': 'active'})
        self.mum = {'X-Member-Token': storage.create_member_token('mum', proof='password', minted_on='personal')}
        self.kid = {'X-Member-Token': storage.create_member_token('kid', proof='pin', minted_on='personal')}
        self.panel = {'X-Device-Token': storage.enrol_device_token('panel-1', 'Kitchen panel', by_member='mum')}
        # Local grace off: a caller with no proof is nobody (401), not Argyle on the LAN.
        self.patch = patch.object(storage, 'get_settings', side_effect=lambda: {
            **_real_settings(), 'auth_enforce': True, 'service_local_grace': False})
        self.patch.start()
        self.client = TestClient(main.app)
        return self

    def __exit__(self, *exc):
        self.patch.stop()

    def upload(self, key, page, body, who=None, content_type='image/png'):
        return self.client.post(page_url(key, page), content=body,
                                headers={**(self.mum if who is None else who), 'Content-Type': content_type})

    def put_manifest(self, key, body, who=None):
        return self.client.put(manifest_url(key), json=body, headers=self.mum if who is None else who)


# ---------------------------------------------------------------- tests

def test_routes_have_their_tiers():
    for method, template, tier in (('POST', PAGE_TEMPLATE, auth.PARENTS), ('GET', PAGE_TEMPLATE, auth.WALL_OR_SERVICE),
                                   ('GET', MANIFEST_TEMPLATE, auth.WALL_OR_SERVICE), ('PUT', MANIFEST_TEMPLATE, auth.PARENTS)):
        check(auth.resolve(method, template) == tier, f'{method} {template}: {auth.resolve(method, template)}')
    import main
    served = {(m, r.path) for r in main.app.routes for m in (getattr(r, 'methods', None) or ())}
    for method, template in (('POST', PAGE_TEMPLATE), ('GET', PAGE_TEMPLATE), ('GET', MANIFEST_TEMPLATE), ('PUT', MANIFEST_TEMPLATE)):
        check((method, template) in served, f'the app serves {method} {template}')


def test_upload_then_download_with_etag():
    key, first, second = key_of(1), png(seed=1), png(seed=2)
    with Ctx() as c:
        r = c.upload(key, 0, first)
        check(r.status_code == 200, (r.status_code, r.text))
        etag = r.json().get('etag')
        check(isinstance(etag, str) and etag, f'the upload answers its etag: {r.text}')
        with open(stored_path(key, 0), 'rb') as f:
            check(f.read() == first, 'the page is stored at DATA_DIR/bakes/<key>/0.png, byte for byte')

        got = c.client.get(page_url(key, 0), headers=c.mum)
        check(got.status_code == 200 and got.content == first, (got.status_code, len(got.content)))
        check(got.headers.get('content-type', '').startswith('image/png'), got.headers.get('content-type'))
        check(got.headers.get('etag') == etag, ('the GET carries the upload\'s etag', got.headers.get('etag'), etag))

        same = c.client.get(page_url(key, 0), headers={**c.mum, 'If-None-Match': etag})
        check(same.status_code == 304 and not same.content, ('unchanged page: 304, no body', same.status_code, len(same.content)))

        r = c.upload(key, 0, second)
        check(r.status_code == 200, (r.status_code, r.text))
        fresh = c.client.get(page_url(key, 0), headers={**c.mum, 'If-None-Match': etag})
        check(fresh.status_code == 200 and fresh.content == second, ('new bytes after a rewrite', fresh.status_code))
        check(fresh.headers.get('etag') not in (None, etag) and fresh.headers.get('etag') == r.json().get('etag'),
              ('new bytes, new etag', etag, fresh.headers.get('etag'), r.text))

        # Pages are independent; a page never written is 404.
        r = c.upload(key, 1, first)
        check(r.status_code == 200, r.text)
        check(c.client.get(page_url(key, 1), headers=c.mum).content == first, 'page 1 holds its own bytes')
        check(c.client.get(page_url(key, 0), headers=c.mum).content == second, 'page 0 untouched by page 1')
        check(c.client.get(page_url(key, 7), headers=c.mum).status_code == 404, 'a page never written is 404')
        check(c.client.get(page_url(key_of(99), 0), headers=c.mum).status_code == 404, 'an unknown key is 404')
        left = sorted(os.listdir(os.path.join(bakes_dir(), key)))
        check(all(STORED.match(n) for n in left), f'nothing but pages (and a manifest) in the key folder: {left}')


def test_manifest_round_trip_and_checks():
    key = key_of(2)
    with Ctx() as c:
        check(c.client.get(manifest_url(key), headers=c.mum).status_code == 404, 'no manifest yet: 404')
        body = manifest()
        r = c.put_manifest(key, body)
        check(r.status_code == 200, (r.status_code, r.text))
        got = c.client.get(manifest_url(key), headers=c.mum)
        check(got.status_code == 200, (got.status_code, got.text))
        data = got.json()
        check({k: data.get(k) for k in ('pages', 'lights', 'sky')} == body, ('the manifest round-trips', data))

        # A newer manifest replaces the old one whole (a light gone is gone).
        smaller = manifest()
        del smaller['lights']['dev-hall']
        check(c.put_manifest(key, smaller).status_code == 200, 'replace the manifest')
        check(c.client.get(manifest_url(key), headers=c.mum).json()['lights'] == smaller['lights'], 'replaced whole')

        bad = []
        m = manifest(); m['lights']['dev-k-light']['channel'] = 4; bad.append(('channel 4', m))
        m = manifest(); m['lights']['dev-k-light']['channel'] = -1; bad.append(('channel -1', m))
        m = manifest(); m['sky']['channel'] = 5; bad.append(('sky channel 5', m))
        m = manifest(pages=2); m['lights']['dev-k-light']['page'] = 2; bad.append(('page past pages', m))
        m = manifest(); m['lights']['dev-k-light']['key'] = '../../x'; bad.append(('light key not a key', m))
        m = manifest(); m['pages'] = 0; bad.append(('no pages', m))
        m = manifest(); m['lights'] = ['dev-k-light']; bad.append(('lights not a map', m))
        bad.append(('not an object', [1, 2, 3]))
        for why, body_ in bad:
            r = c.put_manifest(key, body_)
            check(r.status_code in (400, 422), (why, r.status_code, r.text))
        check(c.client.get(manifest_url(key), headers=c.mum).json()['lights'] == smaller['lights'],
              'a refused manifest left the stored one alone')


def test_non_parent_upload_is_refused():
    key = key_of(3)
    with Ctx() as c:
        for who, name, status in ((c.kid, 'a child', 403), (c.panel, 'the wall panel', 403), ({}, 'nobody', 401)):
            r = c.upload(key, 0, png(), who=who)
            check(r.status_code == status, (name, 'upload', r.status_code, r.text))
            r = c.put_manifest(key, manifest(), who=who)
            check(r.status_code == status, (name, 'manifest', r.status_code, r.text))
        check(not os.path.exists(os.path.join(bakes_dir(), key)), 'nothing was written for a refused caller')
        check(c.client.get(manifest_url(key), headers=c.mum).status_code == 404, 'no manifest from a refused caller')


def test_bad_key_and_oversize_refused():
    good = key_of(4)
    bad_keys = ('abc', 'ABCDEF0123456789ABCDEF', 'g' * 32, 'a' * 65, '0123456789abcdef_x', '0123456789abcde.')
    with Ctx() as c:
        before = set(os.listdir(twin_store.DATA_DIR)) if os.path.isdir(twin_store.DATA_DIR) else set()
        for key in bad_keys:
            r = c.upload(key, 0, png())
            check(r.status_code == 400, ('upload under a bad key', key, r.status_code, r.text))
            r = c.put_manifest(key, manifest())
            check(r.status_code == 400, ('manifest under a bad key', key, r.status_code, r.text))
            for url in (page_url(key, 0), manifest_url(key)):
                r = c.client.get(url, headers=c.mum)
                check(r.status_code in (400, 404), ('read under a bad key', url, r.status_code))
        # Traversal never escapes, whatever the router makes of it.
        for raw in ('%2e%2e', '..%2f..%2fx', '%2e%2e%2f%2e%2e'):
            r = c.client.post(f'/api/house/bakes/{raw}/0.png', content=png(),
                              headers={**c.mum, 'Content-Type': 'image/png'})
            check(r.status_code in (400, 404), ('traversal key', raw, r.status_code))
        for page in ('x', '-1', '1e3', '0x1'):
            r = c.client.post(f'/api/house/bakes/{good}/{page}.png', content=png(),
                              headers={**c.mum, 'Content-Type': 'image/png'})
            check(r.status_code in (400, 404, 422), ('bad page', page, r.status_code))
        check(not os.path.exists(os.path.join(bakes_dir(), good)), 'nothing stored under a good key with a bad page')

        r = c.upload(good, 0, b'GIF89a not a png at all')
        check(r.status_code in (400, 415), ('a body that is not a PNG', r.status_code, r.text))
        r = c.upload(good, 0, PNG_SIG + b'\0' * (CAP + 1 - len(PNG_SIG)))
        check(r.status_code == 413, ('over 16 MiB', r.status_code, r.text[:200]))
        check(not os.path.exists(stored_path(good, 0)), 'an oversize or non-PNG upload stores nothing')
        after = set(os.listdir(twin_store.DATA_DIR)) if os.path.isdir(twin_store.DATA_DIR) else set()
        check(after - before <= {'bakes'}, f'nothing written beside the bakes folder: {sorted(after - before)}')
        if os.path.isdir(bakes_dir()):
            check(all(re.match(r'^[0-9a-f]{16,64}$', n) for n in os.listdir(bakes_dir())),
                  f'only key folders under bakes: {os.listdir(bakes_dir())}')


def test_concurrent_uploads_never_tear_a_page():
    key = key_of(5)
    a, b = png(size=900, noise=True), png(size=900, noise=True)
    check(a != b and len(a) > 2_000_000, 'two big, different pages')
    with Ctx() as c:
        check(c.upload(key, 0, a).status_code == 200, 'seed the page')
        failures, seen, done = [], [], threading.Event()

        def writer(body, n):
            for _ in range(n):
                r = c.upload(key, 0, body)
                if r.status_code != 200:
                    failures.append(('upload', r.status_code, r.text[:200]))

        def reader():
            while not done.is_set():
                r = c.client.get(page_url(key, 0), headers=c.panel)
                if r.status_code != 200:
                    failures.append(('read', r.status_code, r.text[:200]))
                elif r.content == a:
                    seen.append('a')
                elif r.content == b:
                    seen.append('b')
                else:
                    failures.append(('torn read', len(r.content)))

        readers = [threading.Thread(target=reader) for _ in range(2)]
        writers = [threading.Thread(target=writer, args=(a, 6)), threading.Thread(target=writer, args=(b, 6))]
        for t in readers + writers:
            t.start()
        for t in writers:
            t.join(timeout=240)
        done.set()
        for t in readers:
            t.join(timeout=60)
        check(not any(t.is_alive() for t in readers + writers), 'every thread finished')
        check(not failures, f'every upload 200 and every read whole: {failures[:5]} ({len(failures)} in all)')
        check(seen, 'the readers read while the writers wrote')

        last = c.client.get(page_url(key, 0), headers=c.panel)
        check(last.status_code == 200 and last.content in (a, b), 'the page ends whole, one of the uploads')
        again = c.client.get(page_url(key, 0), headers={**c.panel, 'If-None-Match': last.headers.get('etag', '')})
        check(again.status_code == 304, ('the final etag names the final bytes', again.status_code))
        # Both writers end on the same key with one page: no temp files left behind.
        left = sorted(os.listdir(os.path.join(bakes_dir(), key)))
        check(left == ['0.png'], f'one page and no leftovers: {left}')


def test_prune_keeps_only_live_keys():
    from services import twin_bakes
    keys = [key_of(0x60 + i) for i in range(3)]
    with Ctx() as c:
        for k in keys:
            check(c.upload(k, 0, png(seed=3)).status_code == 200, 'seed a page')
            check(c.upload(k, 1, png(seed=4)).status_code == 200, 'seed a second page')
            check(c.put_manifest(k, manifest()).status_code == 200, 'seed a manifest')
        rounds = os.path.join(twin_store.DATA_DIR, 'keep-me.txt')
        with open(rounds, 'w', encoding='utf-8') as f:
            f.write('not a bake')
        twin_bakes.prune({keys[1]})
        for k in (keys[0], keys[2]):
            check(not os.path.exists(os.path.join(bakes_dir(), k)), f'{k} pruned from disk')
            check(c.client.get(page_url(k, 0), headers=c.panel).status_code == 404, 'a pruned page is 404')
            check(c.client.get(manifest_url(k), headers=c.panel).status_code == 404, 'a pruned manifest is 404')
        check(c.client.get(page_url(keys[1], 1), headers=c.panel).content == png(seed=4), 'the live key keeps its pages')
        check(c.client.get(manifest_url(keys[1]), headers=c.panel).status_code == 200, 'the live key keeps its manifest')
        check(os.path.exists(rounds), 'prune touches nothing outside the bakes folder')
        twin_bakes.prune([keys[1]])
        check(os.path.exists(stored_path(keys[1], 0)), 'a list of live keys works the same, and again is harmless')
        twin_bakes.prune(set())
        check(not os.path.exists(os.path.join(bakes_dir(), keys[1])), 'no live keys: every bake goes')
        check(os.path.exists(rounds), 'still nothing outside the bakes folder')


def test_wall_panel_can_read():
    key, body = key_of(7), png(seed=7)
    with Ctx() as c:
        check(c.upload(key, 0, body).status_code == 200, 'seed a page')
        check(c.put_manifest(key, manifest()).status_code == 200, 'seed a manifest')
        for who, name in ((c.panel, 'the wall panel'), (c.kid, 'a child')):
            r = c.client.get(page_url(key, 0), headers=who)
            check(r.status_code == 200 and r.content == body and r.headers.get('etag'), (name, r.status_code))
            r2 = c.client.get(page_url(key, 0), headers={**who, 'If-None-Match': r.headers['etag']})
            check(r2.status_code == 304, (name, 'revalidates', r2.status_code))
            m = c.client.get(manifest_url(key), headers=who)
            check(m.status_code == 200 and m.json().get('lights') == manifest()['lights'], (name, 'manifest', m.status_code))
            # A partial bake (Review Focus 3): a missing page is a plain 404, never an error.
            check(c.client.get(page_url(key, 3), headers=who).status_code == 404, (name, 'missing page 404'))
            check(c.client.get(manifest_url(key_of(0x77)), headers=who).status_code == 404, (name, 'missing manifest 404'))
        check(c.client.get(page_url(key, 0)).status_code == 401, 'nobody signed in reads nothing')
        check(c.client.get(manifest_url(key)).status_code == 401, 'nobody signed in reads no manifest')


def test_ktx2_magic_and_content_type():
    key = key_of(0x81)
    body = b'\xabKTX 20\xbb\r\n\x1a\n' + bytes(range(128))
    with Ctx() as c:
        r = c.upload(key, 0, body, content_type='application/octet-stream')
        check(r.status_code == 200, ('KTX2 magic accepted independently of MIME', r.text))
        got = c.client.get(page_url(key, 0), headers=c.panel)
        check(got.content == body, 'KTX2 round trips byte for byte')
        check(got.headers['content-type'].startswith('image/ktx2'), got.headers)
        check(c.upload(key, 1, b'KTX 20 fake', content_type='image/ktx2').status_code == 400,
              'MIME without the complete magic is refused')


def test_manifest_formats_and_densities():
    import copy
    body = {**manifest(), 'formats': ['ktx2', 'png'], 'densities': {'sky': 2, 'room': 8}}
    with Ctx() as c:
        key = key_of(0x82)
        check(c.put_manifest(key, body).status_code == 200, 'new manifest accepted')
        check(c.client.get(manifest_url(key), headers=c.panel).json() == body, 'metadata round trips')
        for field, value in [('formats', ['ktx2']), ('formats', ['gif', 'png']),
                             ('densities', {'sky': 0, 'room': 8}),
                             ('densities', {'sky': 2, 'room': -1}),
                             ('densities', {'sky': 2}), ('densities', {'sky': True, 'room': 8})]:
            bad = copy.deepcopy(body); bad[field] = value
            check(c.put_manifest(key, bad).status_code == 400, (field, value))
        check(c.client.get(manifest_url(key), headers=c.panel).json() == body, 'bad metadata changes nothing')


TESTS = (
    test_routes_have_their_tiers,
    test_upload_then_download_with_etag,
    test_manifest_round_trip_and_checks,
    test_non_parent_upload_is_refused,
    test_bad_key_and_oversize_refused,
    test_concurrent_uploads_never_tear_a_page,
    test_prune_keeps_only_live_keys,
    test_wall_panel_can_read,
    test_ktx2_magic_and_content_type,
    test_manifest_formats_and_densities,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__)
            traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
