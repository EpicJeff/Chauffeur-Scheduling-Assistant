"""Online material sources (Poly Haven, ambientCG) through the real HTTP routes,
the real download worker and the real ingest path. All HTTP goes through a fake
`_urlopen`, so no test touches the network."""
import io
import json
import struct
import sys
import threading
import time
import traceback
import zipfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request

from PIL import Image
from test_twin_ha_routes import Ctx, seed, ts
from services import auth, twin_materials as materials
from services import twin_material_sources as sources

API = '/api/house/materials'
MB = 1024 * 1024


# --- fake network ------------------------------------------------------------

class FakeResponse:
    """Like http.client's buffered response: read1 returns what one socket read has
    (at most n); read(n) keeps reading until it has n bytes or the stream ends."""

    def __init__(self, chunks, on_read=None, on_close=None):
        self._chunks = iter(chunks)
        self._on_read = on_read
        self._on_close = on_close
        self._pending = b''
        self.headers = {}
        self.reads = 0

    def read1(self, n=-1):
        if not self._pending:
            self.reads += 1
            if self._on_read:
                self._on_read()
            self._pending = next(self._chunks, b'')
        n = len(self._pending) if n is None or n < 0 else n
        out, self._pending = self._pending[:n], self._pending[n:]
        return out

    def read(self, n=-1):
        out = bytearray()
        while n is None or n < 0 or len(out) < n:
            chunk = self.read1(-1 if n is None or n < 0 else n - len(out))
            if not chunk:
                break
            out += chunk
        return bytes(out)

    def close(self):
        if self._on_close:
            self._on_close()
            self._on_close = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeNet:
    """url -> bytes | callable returning a FakeResponse. Unknown urls are offline."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, request, timeout=None):
        url = request.full_url
        assert request.get_header('User-agent'), 'every request names us'
        assert timeout and timeout > 0, 'every request carries a socket timeout'
        with self.lock:
            self.calls.append(url)
        if url not in self.routes:
            raise URLError('offline')
        value = self.routes[url]
        if callable(value):
            return value()
        return FakeResponse([value[i:i + 65536] for i in range(0, len(value), 65536)] or [b''])

    def fetched(self, fragment):
        with self.lock:
            return [u for u in self.calls if fragment in u]


def image(color=(120, 60, 40), fmt='PNG', size=(32, 32)):
    out = io.BytesIO()
    Image.new('RGB', size, color).save(out, format=fmt)
    return out.getvalue()


def endless(chunk=MB):
    block = b'\0' * chunk
    while True:
        yield block


# --- Poly Haven fixtures -----------------------------------------------------

PH_ASSETS = 'https://api.polyhaven.com/assets?t=textures'


def ph_url(slug, token, res, fmt):
    return f'https://dl.polyhaven.org/file/ph-assets/Textures/{fmt}/{res}/{slug}/{slug}_{token}_{res}.{fmt}'


def ph_assets(*slugs):
    return {slug: {'type': 1, 'name': slug.replace('_', ' ').title(), 'tags': ['wall', 'red'],
                   'categories': ['brick', 'outdoor'], 'dimensions': [2438.4, 1219.2],
                   'max_resolution': [2048, 2048], 'download_count': 10 + i,
                   'thumbnail_url': f'https://cdn.polyhaven.com/asset_img/thumbs/{slug}.png?width=256&height=256&format=webp&v=1'}
            for i, slug in enumerate(slugs)}


def ph_files(slug, resolutions=('1k', '2k'), maps=(('Diffuse', 'diff'), ('nor_gl', 'nor_gl'),
                                                   ('Rough', 'rough'), ('arm', 'arm'))):
    files = {}
    for key, token in maps:
        files[key] = {res: {fmt: {'url': ph_url(slug, token, res, fmt), 'size': 2000, 'md5': 'x'}
                            for fmt in ('jpg', 'png', 'exr')} for res in resolutions}
    files['blend'] = {res: {'blend': {'url': f'https://dl.polyhaven.org/{slug}_{res}.blend', 'size': 10}}
                      for res in resolutions}
    files['gltf'] = {res: {'gltf': {'url': f'https://dl.polyhaven.org/{slug}_{res}.gltf', 'size': 10}}
                     for res in resolutions}
    return files


def ph_routes(slug, resolutions=('1k', '2k'), **kw):
    files = ph_files(slug, resolutions, **kw)
    routes = {PH_ASSETS: json.dumps(ph_assets(slug)).encode(),
              f'https://api.polyhaven.com/files/{slug}': json.dumps(files).encode(),
              f'https://api.polyhaven.com/info/{slug}': json.dumps(ph_assets(slug)[slug]).encode()}
    for key, by_res in files.items():
        for res, by_fmt in by_res.items():
            for fmt, entry in by_fmt.items():
                if fmt in ('jpg', 'png'):
                    routes[entry['url']] = image(fmt='JPEG' if fmt == 'jpg' else 'PNG')
    return routes


# --- ambientCG fixtures ------------------------------------------------------

def acg_search_url(q):
    return f'https://ambientcg.com/api/v2/full_json?type=Material&q={q}&include=downloadData'


def acg_asset_url(asset_id):
    return f'https://ambientcg.com/api/v2/full_json?type=Material&id={asset_id}&include=downloadData'


def acg_asset(asset_id, sizes=(('1K-JPG', 5 * MB), ('2K-JPG', 16 * MB), ('4K-JPG', 128 * MB),
                               ('1K-PNG', 9 * MB))):
    return {'assetId': asset_id, 'displayName': asset_id.rstrip('0123456789') + ' ' + asset_id[-3:],
            'category': None, 'displayCategory': 'Bricks', 'tags': ['brick', 'wall'],
            'dimensionX': 200, 'dimensionY': 100,
            'previewImage': {'256-PNG': f'https://acg-media.struffelproductions.com/file/ambientCG-Web/media/thumbnail/256-PNG/{asset_id}.png'},
            'downloadFolders': {'default': {'downloadFiletypeCategories': {'zip': {'downloads': [
                {'downloadLink': f'https://ambientcg.com/get?file={asset_id}_{attr}.zip',
                 'fullDownloadPath': f'https://ambientcg.com/get?file={asset_id}_{attr}.zip',
                 'fileName': f'{asset_id}_{attr}.zip', 'size': size, 'filetype': 'zip', 'attribute': attr}
                for attr, size in sizes]}}}}}


def acg_zip(asset_id, extra=(), maps=('Color', 'NormalGL', 'NormalDX', 'Roughness', 'Metalness',
                                      'AmbientOcclusion', 'Displacement')):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as archive:
        for name in maps:
            archive.writestr(f'{asset_id}_1K-JPG_{name}.jpg', image(fmt='JPEG'))
        archive.writestr(f'{asset_id}_1K-JPG.blend', b'blend')
        archive.writestr(f'{asset_id}_1K-JPG.mtlx', b'<mtlx/>')
        archive.writestr(f'{asset_id}.png', image())
        for name, data in extra:
            archive.writestr(name, data)
    return out.getvalue()


def acg_routes(asset_id, archive=None, **kw):
    payload = {'foundAssets': [acg_asset(asset_id, **kw)]}
    return {acg_asset_url(asset_id): json.dumps(payload).encode(),
            f'https://ambientcg.com/get?file={asset_id}_1K-JPG.zip': archive or acg_zip(asset_id)}


# --- helpers -----------------------------------------------------------------

def reset():
    seed()
    sources._clear_caches()


def folders():
    root = materials.root()
    return {p.name for p in root.iterdir() if p.is_dir()} if root.exists() else set()


def staging_left():
    root = sources.staging_root()
    return list(root.iterdir()) if root.exists() else []


def download(c, source, sid, resolution='1k', headers=None):
    r = c.client.post(f'{API}/sources/{source}/{sid}/download', headers=headers or c.mum,
                      json={'resolution': resolution})
    assert r.status_code == 200, r.text
    return r.json()['job_id']


def wait(c, job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        r = c.client.get(f'{API}/jobs/{job_id}', headers=c.mum)
        assert r.status_code == 200, r.text
        job = r.json()
        assert 0 <= job['progress'] <= 1, job
        if job['state'] in ('done', 'failed'):
            return job
        time.sleep(0.02)
    raise AssertionError(f'job {job_id} never finished')


def refused(c, net, source, sid, words, resolution='1k'):
    before = folders()
    with patch.object(sources, '_urlopen', net):
        job = wait(c, download(c, source, sid, resolution))
    assert job['state'] == 'failed', job
    assert 'material_id' not in job or not job['material_id'], job
    assert any(w.lower() in job['error'].lower() for w in words), job['error']
    assert folders() == before, 'a failed download left a material folder behind'
    assert not staging_left(), 'a failed download left staging behind'
    assert all(row['source'] != source for row in materials.catalogue(True)['materials'])
    return job


def forge_sizes(data, name, size):
    """Rewrite one entry's uncompressed size in both its local and central headers."""
    data = bytearray(data)
    encoded = name.encode()
    pos = 0
    while True:
        pos = data.find(b'PK\x03\x04', pos)
        if pos < 0:
            break
        if data[pos + 30:pos + 30 + len(encoded)] == encoded:
            struct.pack_into('<I', data, pos + 22, size)
        pos += 4
    pos = 0
    while True:
        pos = data.find(b'PK\x01\x02', pos)
        if pos < 0:
            break
        if data[pos + 46:pos + 46 + len(encoded)] == encoded:
            struct.pack_into('<I', data, pos + 24, size)
        pos += 4
    return bytes(data)


# --- tests -------------------------------------------------------------------

def test_polyhaven_download_maps_slots():
    reset()
    net = FakeNet(ph_routes('red_brick_03'))
    with Ctx() as c, patch.object(sources, '_urlopen', net):
        before = folders()
        job = wait(c, download(c, 'polyhaven', 'red_brick_03', '2k'))
        assert job['state'] == 'done', job
        record = materials.get(job['material_id'])
        assert set(record['maps']) == {'base_color', 'normal', 'roughness', 'orm'}, record['maps']
        assert record['params']['normal_convention'] == 'gl'
        assert record['source'] == 'polyhaven' and record['licence'] == 'CC0'
        assert record['source_url'] == 'https://polyhaven.com/a/red_brick_03'
        assert record['name'] == 'Red Brick 03'
        assert record['source_snapshot'] == {'maps': record['maps'], 'params': record['params']}
        assert record['params']['tile_ft'] == [8, 4], record['params']['tile_ft']  # 2438.4 x 1219.2 mm
        assert folders() - before == {record['id']}
        assert not staging_left()
        # Only the chosen resolution, only images, base colour as JPEG, data maps as PNG.
        downloads = net.fetched('dl.polyhaven.org')
        assert downloads and all('_2k.' in u for u in downloads), downloads
        assert not any(u.endswith(('.exr', '.blend', '.gltf')) for u in downloads), downloads
        assert ph_url('red_brick_03', 'diff', '2k', 'jpg') in downloads
        assert ph_url('red_brick_03', 'nor_gl', '2k', 'png') in downloads
        # Published through the real file route and listed in the Library.
        row = next(r for r in c.client.get(API, headers=c.mum).json()['materials'] if r['id'] == record['id'])
        assert row['source'] == 'polyhaven'
        r = c.client.get(f"/api/house/twin/materials/{record['id']}/{record['maps']['normal']}", headers=c.panel)
        assert r.status_code == 200 and r.content[:4] == b'\x89PNG'
        assert materials.reset_to_source(record['id'], 'mum')['maps'] == record['maps']


def test_ambientcg_zip_download_maps_slots():
    reset()
    net = FakeNet(acg_routes('Bricks097'))
    with Ctx() as c, patch.object(sources, '_urlopen', net):
        ingested = []
        real = materials.ingest_image

        def spy(mid, slot, data, **kw):
            ingested.append(slot)
            return real(mid, slot, data, **kw)
        with patch.object(materials, 'ingest_image', spy):
            job = wait(c, download(c, 'ambientcg', 'Bricks097', '1k'))
        assert job['state'] == 'done', job
        record = materials.get(job['material_id'])
        assert set(record['maps']) == {'base_color', 'normal', 'roughness', 'metalness', 'ao', 'height'}
        assert sorted(ingested) == sorted(record['maps']), 'only mapped image entries are ingested'
        assert record['params']['normal_convention'] == 'gl', 'NormalGL wins over NormalDX'
        assert record['source'] == 'ambientcg' and record['licence'] == 'CC0'
        assert record['source_url'] == 'https://ambientcg.com/a/Bricks097'
        assert record['source_snapshot']['maps'] == record['maps']
        assert abs(record['params']['tile_ft'][0] - 200 / 30.48) < 1e-3
        assert not staging_left()
        assert 'https://ambientcg.com/get?file=Bricks097_1K-JPG.zip' in net.calls


def test_ambientcg_dx_only_normal_keeps_dx_convention():
    reset()
    archive = acg_zip('Planks012', maps=('Color', 'NormalDX', 'Roughness'))
    net = FakeNet(acg_routes('Planks012', archive))
    with Ctx() as c, patch.object(sources, '_urlopen', net):
        job = wait(c, download(c, 'ambientcg', 'Planks012'))
        assert job['state'] == 'done', job
        record = materials.get(job['material_id'])
        assert record['params']['normal_convention'] == 'dx'
        assert set(record['maps']) == {'base_color', 'normal', 'roughness'}


def test_zip_traversal_refused_nothing_published():
    reset()
    with Ctx() as c:
        for bad in ('../Bricks001_1K-JPG_Color.jpg', 'maps/../../evil.jpg', '/etc/Bricks001_Color.jpg',
                    'C:/Windows/Bricks001_Color.jpg', 'd:evil.txt', 'a\\..\\..\\evil.jpg'):
            archive = acg_zip('Bricks001', extra=[(bad, image(fmt='JPEG'))])
            refused(c, FakeNet(acg_routes('Bricks001', archive)), 'ambientcg', 'Bricks001', ['unsafe'])


def test_zip_bomb_refused():
    reset()
    with Ctx() as c:
        # A 1 MB entry whose header declares more than the 400 MB expanded cap.
        name = 'Bricks002_1K-JPG_Color.jpg'
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, b'\0' * MB)
        declared = forge_sizes(out.getvalue(), name, 401 * MB)
        assert zipfile.ZipFile(io.BytesIO(declared)).getinfo(name).file_size == 401 * MB
        refused(c, FakeNet(acg_routes('Bricks002', declared)), 'ambientcg', 'Bricks002', ['too large'])
        # A 1 MB-declared entry that really expands past the cap (cap lowered to keep it quick).
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, b'\0' * (3 * MB))
        lying = forge_sizes(out.getvalue(), name, MB)
        with patch.object(sources, 'MAX_ARCHIVE_EXPANDED', 2 * MB):
            refused(c, FakeNet(acg_routes('Bricks002', lying)), 'ambientcg', 'Bricks002',
                    ['too large', 'damaged'])
        # More entries than the cap.
        many = acg_zip('Bricks002', extra=[(f'junk{i}.txt', b'x') for i in range(64)])
        refused(c, FakeNet(acg_routes('Bricks002', many)), 'ambientcg', 'Bricks002', ['too many'])


def test_oversize_stream_refused():
    reset()
    routes = ph_routes('big_wall')
    # The files API declares a small file; the stream itself runs past 64 MB.
    routes[ph_url('big_wall', 'diff', '1k', 'jpg')] = lambda: FakeResponse(endless())
    with Ctx() as c:
        job = refused(c, FakeNet(routes), 'polyhaven', 'big_wall', ['64 MB'])
        assert job['progress'] < 1


def test_job_byte_cap_refused():
    reset()
    with Ctx() as c, patch.object(sources, 'MAX_JOB_BYTES', 2 * MB):
        routes = ph_routes('busy_wall')
        for token, fmt in (('diff', 'jpg'), ('nor_gl', 'png'), ('rough', 'png'), ('arm', 'png')):
            routes[ph_url('busy_wall', token, '1k', fmt)] = lambda: FakeResponse([b'\0' * MB])
        refused(c, FakeNet(routes), 'polyhaven', 'busy_wall', ['larger than 2 MB in all'])


def test_deadline_refused():
    reset()
    clock = [1000.0]

    def tick():
        clock[0] += 100  # each chunk takes 100 s of fake time

    routes = ph_routes('slow_wall')
    routes[ph_url('slow_wall', 'diff', '1k', 'jpg')] = lambda: FakeResponse(endless(1024), on_read=tick)
    with Ctx() as c, patch.object(sources, '_now', lambda: clock[0]):
        refused(c, FakeNet(routes), 'polyhaven', 'slow_wall', ['3 minutes'])


def test_one_job_at_a_time():
    reset()
    gate = threading.Event()
    active, peak, lock = [0], [0], threading.Lock()

    def tracked(data, blocking=False):
        def make():
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])

            def close():
                with lock:
                    active[0] -= 1
            return FakeResponse([data], on_read=(lambda: gate.wait(20)) if blocking else None, on_close=close)
        return make

    routes = {**ph_routes('first_wall'), **ph_routes('second_wall')}
    routes[PH_ASSETS] = json.dumps(ph_assets('first_wall', 'second_wall')).encode()
    for url, data in list(routes.items()):
        if 'dl.polyhaven.org' in url:
            routes[url] = tracked(data, blocking='first_wall_diff' in url)
    net = FakeNet(routes)
    with Ctx() as c, patch.object(sources, '_urlopen', net):
        try:
            first = download(c, 'polyhaven', 'first_wall')
            second = download(c, 'polyhaven', 'second_wall')
            end = time.time() + 10
            while c.client.get(f'{API}/jobs/{first}', headers=c.mum).json()['state'] != 'running':
                assert time.time() < end
                time.sleep(0.01)
            time.sleep(0.2)
            assert c.client.get(f'{API}/jobs/{second}', headers=c.mum).json()['state'] == 'queued'
            assert not net.fetched('second_wall'), 'the queued job must not start fetching'
        finally:
            gate.set()
        done = [wait(c, first), wait(c, second)]
        assert all(j['state'] == 'done' for j in done), done
        assert done[0]['material_id'] != done[1]['material_id']
        assert peak[0] == 1, f'{peak[0]} downloads ran at once'


def test_offline_search_503_message():
    reset()
    net = FakeNet()  # every url is offline
    with Ctx() as c, patch.object(sources, '_urlopen', net):
        for source in ('polyhaven', 'ambientcg'):
            r = c.client.get(f'{API}/sources/{source}', params={'q': 'brick'}, headers=c.mum)
            assert r.status_code == 503, r.text
            assert r.json()['detail'] == 'Online libraries are not reachable.'
        assert c.client.get(f'{API}/sources/polyhaven/red_brick_03/thumb', headers=c.mum).status_code == 503
        # The rest of the Library keeps working.
        assert c.client.get(API, headers=c.mum).status_code == 200
        assert c.client.get(f'{API}/sources/textures.com', headers=c.mum).status_code == 404


def test_search_filters_and_caches_ten_minutes():
    reset()
    clock = [5000.0]
    assets = ph_assets('red_brick_03', 'oak_planks', 'grey_brick')
    assets['oak_planks'].update(categories=['wood'], tags=['floor'])
    assets['grey_brick']['max_resolution'] = [4096, 4096]
    q_url = acg_search_url('red%20brick')
    huge = acg_asset('Ground111', sizes=(('1K-JPG', 9 * MB), ('2K-JPG', 34 * MB), ('4K-JPG', 260 * MB),
                                         ('4K-PNG', 500 * MB)))
    net = FakeNet({PH_ASSETS: json.dumps(assets).encode(),
                   q_url: json.dumps({'foundAssets': [acg_asset('Bricks097'), huge]}).encode()})
    with Ctx() as c, patch.object(sources, '_urlopen', net), patch.object(sources, '_now', lambda: clock[0]):
        rows = c.client.get(f'{API}/sources/polyhaven', params={'q': 'brick'}, headers=c.mum).json()['results']
        assert [r['source_id'] for r in rows] == ['grey_brick', 'red_brick_03'], rows  # most downloaded first
        row = rows[1]
        assert row == {'source': 'polyhaven', 'source_id': 'red_brick_03', 'name': 'Red Brick 03',
                       'thumbnail': 'api/house/materials/sources/polyhaven/red_brick_03/thumb',
                       'resolutions': ['1k', '2k'], 'source_url': 'https://polyhaven.com/a/red_brick_03'}, row
        assert rows[0]['resolutions'] == ['1k', '2k', '4k']
        assert not any(r['thumbnail'].startswith('/') for r in rows), 'no root-relative urls under ingress'
        wood = c.client.get(f'{API}/sources/polyhaven', params={'category': 'Wood'}, headers=c.mum).json()['results']
        assert [r['source_id'] for r in wood] == ['oak_planks']
        assert len(net.fetched('api.polyhaven.com')) == 1, 'search is cached'
        clock[0] += 599
        c.client.get(f'{API}/sources/polyhaven', params={'q': 'oak'}, headers=c.mum)
        assert len(net.fetched('api.polyhaven.com')) == 1
        clock[0] += 2
        c.client.get(f'{API}/sources/polyhaven', params={'q': 'oak'}, headers=c.mum)
        assert len(net.fetched('api.polyhaven.com')) == 2, 'the cache expires after 10 minutes'
        acg = c.client.get(f'{API}/sources/ambientcg', params={'q': 'red brick'}, headers=c.mum)
        assert acg.status_code == 200, acg.text
        assert net.calls[-1] == q_url
        row, big = acg.json()['results']
        assert row['source_id'] == 'Bricks097' and row['source'] == 'ambientcg'
        # A 128 MB 4K zip is within the 200 MB archive cap; 260 MB JPG / 500 MB PNG is not.
        assert row['resolutions'] == ['1k', '2k', '4k'], row
        assert big['resolutions'] == ['1k', '2k'], big
        assert row['thumbnail'] == 'api/house/materials/sources/ambientcg/Bricks097/thumb'
        c.client.get(f'{API}/sources/ambientcg', params={'q': 'red brick'}, headers=c.mum)
        assert len(net.fetched('ambientcg.com')) == 1


def test_thumbnail_proxied_and_cached_on_disk():
    reset()
    assets = ph_assets('red_brick_03')
    upstream = assets['red_brick_03']['thumbnail_url']
    webp = io.BytesIO()
    Image.new('RGB', (300, 300), (200, 10, 10)).save(webp, format='WEBP')
    net = FakeNet({PH_ASSETS: json.dumps(assets).encode(), upstream: webp.getvalue(),
                   'https://acg-media.struffelproductions.com/file/ambientCG-Web/media/thumbnail/256-PNG/Bricks097.png': image()})
    with Ctx() as c, patch.object(sources, '_urlopen', net):
        c.client.get(f'{API}/sources/polyhaven', headers=c.mum)
        url = f'{API}/sources/polyhaven/red_brick_03/thumb'
        r = c.client.get(url, headers=c.mum)
        assert r.status_code == 200, r.text
        assert r.headers['content-type'] == 'image/png'
        with Image.open(io.BytesIO(r.content)) as thumb:
            assert max(thumb.size) <= 256
        assert c.client.get(url, headers=c.mum).content == r.content
        assert net.calls.count(upstream) == 1, 'the thumbnail is cached on disk'
        cached = Path(ts.DATA_DIR) / 'material_sources' / 'thumbs'
        assert sorted(p.name for p in cached.iterdir()) == ['polyhaven-red_brick_03.png']
        # Without a search first, ambientCG falls back to its known thumbnail address.
        assert c.client.get(f'{API}/sources/ambientcg/Bricks097/thumb', headers=c.mum).status_code == 200


def test_bad_requests():
    reset()
    with Ctx() as c, patch.object(sources, '_urlopen', FakeNet()):
        r = c.client.post(f'{API}/sources/polyhaven/red_brick_03/download', headers=c.mum, json={'resolution': '8k'})
        assert r.status_code == 400, r.text
        r = c.client.post(f'{API}/sources/textures.com/x/download', headers=c.mum, json={'resolution': '1k'})
        assert r.status_code == 404, r.text
        r = c.client.post(f'{API}/sources/polyhaven/bad%20id!/download', headers=c.mum, json={'resolution': '1k'})
        assert r.status_code == 404, r.text
        assert c.client.get(f'{API}/jobs/nope', headers=c.mum).status_code == 404
        # An upstream url outside the source's own hosts is never fetched.
        try:
            sources._check_url('http://dl.polyhaven.org/x.jpg', 'polyhaven')
        except ValueError:
            pass
        else:
            raise AssertionError('plain http accepted')
        for url in ('https://evil.example/x.jpg', 'https://polyhaven.org.evil.example/x.jpg'):
            try:
                sources._check_url(url, 'polyhaven')
            except ValueError:
                pass
            else:
                raise AssertionError(url)
        sources._check_url('https://cdn.polyhaven.com/a.png', 'polyhaven')


def test_parents_only():
    reset()
    with Ctx() as c, patch.object(sources, '_urlopen', FakeNet(ph_routes('red_brick_03'))):
        routes = [('GET', f'{API}/sources/polyhaven', f'{API}/sources/{{source}}'),
                  ('GET', f'{API}/sources/polyhaven/red_brick_03/thumb', f'{API}/sources/{{source}}/{{source_id}}/thumb'),
                  ('POST', f'{API}/sources/polyhaven/red_brick_03/download',
                   f'{API}/sources/{{source}}/{{source_id}}/download'),
                  ('GET', f'{API}/jobs/some-job', f'{API}/jobs/{{job_id}}')]
        for method, url, template in routes:
            assert auth.resolve(method, template) == auth.PARENTS, (method, template)
            for headers in (c.kid, c.panel, c.visitor):
                r = c.client.request(method, url, headers=headers, json={'resolution': '1k'})
                assert r.status_code in (401, 403), (method, url, headers, r.status_code, r.text)
        assert not net_downloads_started(), 'a refused caller never queues a download'


def test_trickling_server_stops_at_the_deadline():
    """A server sending 512 bytes a second must not hold a 1 MB read open past 3 minutes."""
    reset()
    clock = [1000.0]
    responses = []

    def tick():
        clock[0] += 1

    def trickle():
        responses.append(FakeResponse(endless(512), on_read=tick))
        return responses[-1]

    routes = ph_routes('trickle_wall')
    routes[ph_url('trickle_wall', 'diff', '1k', 'jpg')] = trickle
    with Ctx() as c, patch.object(sources, '_now', lambda: clock[0]):
        refused(c, FakeNet(routes), 'polyhaven', 'trickle_wall', ['3 minutes'])
        assert responses and responses[0].reads <= 182, f'{responses[0].reads} socket reads, deadline overran'
        # Search obeys its own 30 s deadline the same way.
        sources._clear_caches()
        responses.clear()
        net = FakeNet({PH_ASSETS: trickle})
        with patch.object(sources, '_urlopen', net):
            r = c.client.get(f'{API}/sources/polyhaven', headers=c.mum)
        assert r.status_code == 503, r.text
        assert responses[0].reads <= 32, responses[0].reads


def public(*addresses):
    return lambda host, port, **kw: [(2, 1, 6, '', (a, port)) for a in addresses]


def test_redirects_and_addresses_are_guarded():
    handler = sources._GuardedRedirect()

    def hop(req, url):
        return handler.redirect_request(req, None, 302, 'Found', {}, url)

    def refuses(call, words):
        try:
            call()
        except ValueError as exc:
            assert words in str(exc), exc
        else:
            raise AssertionError('not refused')

    start = Request('https://ambientcg.com/get?file=Bricks097_1K-JPG.zip')
    start.chauffeur_source = 'ambientcg'
    with patch.object(sources, '_resolve', public('104.21.3.4')):
        # The live ambientCG hop: get?file= -> acg-download.struffelproductions.com.
        new = hop(start, 'https://acg-download.struffelproductions.com/file/ambientCG-Web/download/x.zip')
        assert new.full_url.startswith('https://acg-download.struffelproductions.com/')
        assert new.chauffeur_source == 'ambientcg' and new.chauffeur_hops == 1
        refuses(lambda: hop(start, 'https://evil.example/x.zip'), "library's own")
        refuses(lambda: hop(start, 'https://ambientcg.com.evil.example/x.zip'), "library's own")
        refuses(lambda: hop(start, 'http://ambientcg.com/x.zip'), "library's own")
        polyhaven = Request('https://dl.polyhaven.org/a.jpg')
        polyhaven.chauffeur_source = 'polyhaven'
        refuses(lambda: hop(polyhaven, 'https://ambientcg.com/a.jpg'), "library's own")
        req = start
        for _ in range(sources.MAX_REDIRECTS):
            req = hop(req, 'https://ambientcg.com/next')
        assert req.chauffeur_hops == 5
        refuses(lambda: hop(req, 'https://ambientcg.com/next'), 'too many')
    for address in ('127.0.0.1', '10.0.0.5', '192.168.1.20', '172.16.0.1', '169.254.169.254',
                    '::1', 'fe80::1', '::ffff:127.0.0.1', '0.0.0.0'):
        with patch.object(sources, '_resolve', public('104.21.3.4', address)):
            refuses(lambda: hop(start, 'https://acg-download.struffelproductions.com/x.zip'), 'public')
            # The first url is checked the same way, before any connection is made.
            refuses(lambda: sources._guarded_urlopen(start, 5), 'public')
    with patch.object(sources, '_resolve', public('104.21.3.4')):
        bad = Request('https://evil.example/x')
        bad.chauffeur_source = 'ambientcg'
        refuses(lambda: sources._guarded_urlopen(bad, 5), "library's own")
    assert sources._urlopen is sources._guarded_urlopen, 'the default opener is the guarded one'


def test_archive_has_its_own_200_mb_cap():
    reset()
    padding = [('padding.bin', b'\1' * (MB + MB // 2))]
    with Ctx() as c:
        # A 1.5 MB zip refused past a (lowered) archive cap, even though it declared less.
        with patch.object(sources, 'MAX_ARCHIVE_BYTES', MB):
            routes = acg_routes('Bricks004', acg_zip('Bricks004', extra=padding), sizes=(('1K-JPG', 1000),))
            refused(c, FakeNet(routes), 'ambientcg', 'Bricks004', ['larger than 1 MB'])
        # The same size passes when files are capped at 1 MB: the zip is not a file.
        with patch.object(sources, 'MAX_FILE_BYTES', MB), \
                patch.object(sources, '_urlopen', FakeNet(acg_routes('Bricks003', acg_zip('Bricks003', extra=padding)))):
            job = wait(c, download(c, 'ambientcg', 'Bricks003'))
            assert job['state'] == 'done', job


def test_metadata_counts_against_the_job_cap():
    reset()
    routes = ph_routes('chatty_wall')
    files = json.loads(routes['https://api.polyhaven.com/files/chatty_wall'])
    files['padding'] = 'x' * (MB + MB // 2)
    routes['https://api.polyhaven.com/files/chatty_wall'] = json.dumps(files).encode()
    with Ctx() as c, patch.object(sources, 'MAX_JOB_BYTES', MB):
        refused(c, FakeNet(routes), 'polyhaven', 'chatty_wall', ['larger than 1 MB in all'])


def test_unreadable_answers_get_plain_messages():
    reset()
    with Ctx() as c:
        routes = ph_routes('garbled_wall')
        routes['https://api.polyhaven.com/files/garbled_wall'] = b'<html>busy</html>'
        job = refused(c, FakeNet(routes), 'polyhaven', 'garbled_wall', ['could not be read'])
        assert job['error'] == 'The library sent an answer that could not be read.'
        routes = ph_routes('broken_wall')
        routes[ph_url('broken_wall', 'diff', '1k', 'jpg')] = b'not an image at all'
        job = refused(c, FakeNet(routes), 'polyhaven', 'broken_wall', ['image'])
        assert job['error'] == 'A downloaded image could not be read.', job['error']
        assert 'BytesIO' not in job['error']


def test_queue_holds_at_most_ten():
    reset()
    gate = threading.Event()
    routes = ph_routes('held_wall')
    data = routes[ph_url('held_wall', 'diff', '1k', 'jpg')]
    routes[ph_url('held_wall', 'diff', '1k', 'jpg')] = lambda: FakeResponse([data], on_read=lambda: gate.wait(20))
    with Ctx() as c, patch.object(sources, '_urlopen', FakeNet(routes)):
        try:
            jobs = [download(c, 'polyhaven', 'held_wall')]
            end = time.time() + 10
            while c.client.get(f'{API}/jobs/{jobs[0]}', headers=c.mum).json()['state'] != 'running':
                assert time.time() < end
                time.sleep(0.01)
            jobs += [download(c, 'polyhaven', 'held_wall') for _ in range(10)]
            r = c.client.post(f'{API}/sources/polyhaven/held_wall/download', headers=c.mum,
                              json={'resolution': '1k'})
            assert r.status_code == 429, r.text
            assert r.json()['detail'] == '10 downloads are already waiting. Try again when some finish.'
        finally:
            gate.set()
        assert all(wait(c, j)['state'] == 'done' for j in jobs)


def test_startup_sweep_clears_unpublished_job_leftovers():
    reset()
    staging = sources.staging_root() / 'old-job'
    staging.mkdir(parents=True)
    (staging / '0.img').write_bytes(b'partial')
    orphan = materials.root() / materials.new_id()
    (orphan / 'maps').mkdir(parents=True)
    (orphan / sources.JOB_MARKER).write_text('old-job')
    unmarked = materials.root() / materials.new_id()
    unmarked.mkdir()
    net = FakeNet(ph_routes('fresh_wall'))
    with Ctx() as c, patch.object(sources, '_urlopen', net), patch.object(sources, '_SWEPT', False):
        published = materials.create({'name': 'Kept'}, 'mum')
        (materials.root() / published['id'] / sources.JOB_MARKER).write_text('done-job')
        job = wait(c, download(c, 'polyhaven', 'fresh_wall'))
        assert job['state'] == 'done', job
        assert not orphan.exists() and not staging.exists(), 'leftovers swept on first start'
        assert unmarked.exists(), 'an unmarked folder is not ours to remove'
        assert materials.get(published['id'])['name'] == 'Kept'
        fresh = materials.root() / job['material_id']
        assert not (fresh / sources.JOB_MARKER).exists(), 'a published download drops its marker'


def net_downloads_started():
    with sources._JOBS_LOCK:
        return [j for j in sources._JOBS.values() if j['source_id'] == 'red_brick_03' and j['state'] == 'queued']


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
            print('ok  ', test.__name__)
        except Exception:
            print('FAIL', test.__name__)
            traceback.print_exc(limit=8)
    print(f'{passed}/{len(tests)} passed')
    sys.exit(passed != len(tests))
