"""Real atlas routes, auth, byte limits and atomic storage in isolated data."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_twin_bakes import Ctx, check, key_of, manifest
from services import auth, twin_bakes, twin_store

URL = '/api/house/atlases/'


def test_routes():
    template = URL + '{key}'
    check(auth.resolve('GET', template) == auth.WALL_OR_SERVICE, 'GET tier')
    check(auth.resolve('PUT', template) == auth.PARENTS, 'PUT tier')
    with Ctx() as c:
        key, data = key_of(101), b'\x1f\x8b\x00opaque atlas\xff'
        check(c.client.get(URL + key, headers=c.panel).status_code == 404, 'unknown atlas')
        r = c.client.put(URL + key, content=data, headers=c.mum)
        check(r.status_code == 200, r.text)
        for who in (c.mum, c.kid, c.panel):
            r = c.client.get(URL + key, headers=who)
            check(r.status_code == 200 and r.content == data, 'exact bytes for every reader')
            check('content-encoding' not in r.headers, 'gzip stays inside the container')
        for who in (c.kid, c.panel):
            check(c.client.put(URL + key, content=b'no', headers=who).status_code == 403, 'non-parent PUT')
        check(c.client.get(URL + key, headers=c.panel).content == data, 'refusals preserve bytes')
        for method in ('get', 'put'):
            for bad in ('bad', 'G' * 32, 'a' * 65, '0123456789abcde.'):
                r = getattr(c.client, method)(URL + bad, headers=c.mum)
                check(r.status_code == 400, (method, bad, r.status_code))
        check(c.client.get(URL + key).status_code == 401, 'anonymous GET')
        check(c.client.put(URL + key, content=data).status_code == 401, 'anonymous PUT')
        cap = twin_bakes.MAX_ATLAS_BYTES
        check(cap == 64 * 1024 * 1024, '64 MiB bound')
        check(c.client.put(URL + key_of(102), content=b'x' * (cap + 1), headers=c.mum).status_code == 413, 'over cap')
        check(c.client.get(URL + key_of(102), headers=c.mum).status_code == 404, 'oversize stores nothing')
        with patch.object(twin_bakes, 'MAX_ATLAS_BYTES', 4):
            check(c.client.put(URL + key, content=b'1234', headers=c.mum).status_code == 200, 'inclusive limit')
            check(c.client.put(URL + key, content=iter([b'123', b'45']), headers=c.mum).status_code == 413, 'stream limit')
            check(c.client.get(URL + key, headers=c.mum).content == b'1234', 'oversize preserves previous')


def test_prune():
    root = Path(twin_store.DATA_DIR) / 'atlases'
    with Ctx() as c:
        # Refreshing an old key makes it newest; only the last N uploads survive.
        keys = [key_of(n) for n in (201, 202, 203, 201)]
        for i, key in enumerate(keys):
            check(c.client.put(URL + key, content=bytes([i]), headers=c.mum).status_code == 200, 'upload')
            os.utime(root / key, (2_000_000_000 + i, 2_000_000_000 + i))
        check({p.name for p in root.iterdir()} == set(keys[-twin_bakes.KEEP_ATLASES:]), 'last two keys')
        check(all(not p.name.startswith('.') for p in root.iterdir()), 'no atomic-write leftovers')
        # Both bake cleanup entry points also bound the atlas folder. Input keys
        # are independent from bake output keys and are not filtered by live_keys.
        for cleanup in (lambda: twin_bakes.prune([]),
                        lambda: twin_bakes.save_manifest(key_of(301), manifest())):
            extra = key_of(204)
            (root / extra).write_bytes(b'old')
            os.utime(root / extra, (1, 1))
            cleanup()
            check({p.name for p in root.iterdir()} == set(keys[-2:]), 'bake cleanup bounds atlases')


if __name__ == '__main__':
    for test in (test_routes, test_prune):
        test()
        print('  ok ', test.__name__)
    print('2/2 passed')
