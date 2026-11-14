"""Bounded online material sources: Poly Haven and ambientCG (both CC0).

Search and thumbnails go through the server so the page never talks to a
third-party host (ingress, CSP), and both are cached. Downloads run as jobs on
one worker thread, one at a time, with streamed reads capped per file and per
job and an overall deadline. ambientCG zips are checked before anything is
extracted. Every image goes through `twin_materials.ingest_image` into a staged
material folder that is published only when the whole job succeeds; any
failure removes the staging. All HTTP goes through `_urlopen` (faked in tests).
"""
from __future__ import annotations

import io
import json
import logging
import queue
import re
import shutil
import threading
import time
import uuid
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from services import twin_materials

log = logging.getLogger(__name__)

SOURCES = ('polyhaven', 'ambientcg')
RESOLUTIONS = ('1k', '2k', '4k')
SEARCH_TTL_S = 600
MAX_RESULTS = 200
MAX_SEARCH_BYTES = 32 * 1024 * 1024
MAX_THUMB_BYTES = 4 * 1024 * 1024
THUMB_SIDE = 256
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_JOB_BYTES = 300 * 1024 * 1024
DEADLINE_S = 180
MAX_ARCHIVE_ENTRIES = 64
MAX_ARCHIVE_EXPANDED = 400 * 1024 * 1024
CHUNK = 1024 * 1024
SOCKET_TIMEOUT_S = 15
MAX_JOBS_KEPT = 50
UNREACHABLE = 'Online libraries are not reachable.'
USER_AGENT = 'Chauffeur-HomeAssistant-addon/1.0 (household material library)'

POLYHAVEN_ASSETS = 'https://api.polyhaven.com/assets?t=textures'
POLYHAVEN_FILES = 'https://api.polyhaven.com/files/{id}'
POLYHAVEN_INFO = 'https://api.polyhaven.com/info/{id}'
POLYHAVEN_THUMB = 'https://cdn.polyhaven.com/asset_img/thumbs/{id}.png?width=256&height=256'
POLYHAVEN_PAGE = 'https://polyhaven.com/a/{id}'
AMBIENTCG_SEARCH = 'https://ambientcg.com/api/v2/full_json?type=Material&q={q}&include=downloadData'
AMBIENTCG_ASSET = 'https://ambientcg.com/api/v2/full_json?type=Material&id={id}&include=downloadData'
AMBIENTCG_THUMB = 'https://acg-media.struffelproductions.com/file/ambientCG-Web/media/thumbnail/256-PNG/{id}.png'
AMBIENTCG_PAGE = 'https://ambientcg.com/a/{id}'
# The first request of any url taken from upstream data must be https on the source's own hosts.
HOSTS = {'polyhaven': ('polyhaven.com', 'polyhaven.org'),
         'ambientcg': ('ambientcg.com', 'struffelproductions.com')}

# Poly Haven files-API keys (and file-name tokens) to slots; normals carry their convention.
POLYHAVEN_SLOTS = {'diffuse': 'base_color', 'diff': 'base_color', 'albedo': 'base_color', 'col': 'base_color',
                   'color': 'base_color', 'nor_gl': ('normal', 'gl'), 'nor_dx': ('normal', 'dx'),
                   'rough': 'roughness', 'roughness': 'roughness', 'metal': 'metalness',
                   'metallic': 'metalness', 'metalness': 'metalness', 'arm': 'orm', 'ao': 'ao',
                   'displacement': 'height', 'disp': 'height'}
# ambientCG zip entries end in _<Map>.jpg|png.
AMBIENTCG_SLOTS = {'color': 'base_color', 'normalgl': ('normal', 'gl'), 'normaldx': ('normal', 'dx'),
                   'roughness': 'roughness', 'metalness': 'metalness', 'ambientocclusion': 'ao',
                   'displacement': 'height'}
IMAGE_SUFFIXES = ('.jpg', '.jpeg', '.png')

_urlopen = urlopen
_now = time.monotonic
on_published = None  # main sets this to its update signal

_CACHE_LOCK = threading.Lock()
_SEARCH = {}       # key -> (expires, value)
_THUMB_URLS = {}   # (source, source_id) -> upstream thumbnail url seen in a search
_JOBS_LOCK = threading.Lock()
_JOBS = {}
_QUEUE = queue.Queue()
_WORKER = None


class UnknownSource(ValueError):
    """Not one of our libraries, or not a valid id there (a 404)."""


class Unreachable(Exception):
    """The library could not be reached or answered nonsense (a 503)."""


class DownloadError(ValueError):
    """A refusal with a message a person can read."""


def _mb(value):
    return f'{value // (1024 * 1024)} MB'


def _source(source):
    if source not in SOURCES:
        raise UnknownSource('No such online library.')
    return source


def _source_id(source_id):
    if not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', source_id):
        raise UnknownSource('No such material in that library.')
    return source_id


def sources_root() -> Path:
    return twin_materials.root().parent / 'material_sources'


def thumbs_root() -> Path:
    return sources_root() / 'thumbs'


def staging_root() -> Path:
    return sources_root() / 'staging'


def _clear_caches():
    with _CACHE_LOCK:
        _SEARCH.clear()
        _THUMB_URLS.clear()


# --- bounded http ------------------------------------------------------------

def _check_url(url, source):
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    if parts.scheme != 'https' or not any(host == h or host.endswith('.' + h) for h in HOSTS[source]):
        raise ValueError('That address is not one of the library\'s own.')
    return url


def _stream(url, source, *, cap, deadline, sink, cap_message, on_bytes=None):
    """Read `url` in chunks into `sink`; refuse past `cap` bytes or the deadline."""
    _check_url(url, source)
    if _now() > deadline:
        raise DownloadError('The download took longer than 3 minutes.')
    remaining = max(1, min(SOCKET_TIMEOUT_S, deadline - _now()))
    request = Request(url, headers={'User-Agent': USER_AGENT})
    total = 0
    with _urlopen(request, timeout=remaining) as response:
        while True:
            chunk = response.read(CHUNK)
            if _now() > deadline:
                raise DownloadError('The download took longer than 3 minutes.')
            if not chunk:
                return total
            total += len(chunk)
            if total > cap:
                raise DownloadError(cap_message)
            if on_bytes:
                on_bytes(len(chunk))
            sink(chunk)


def _bytes(url, source, *, cap, deadline, cap_message='The answer was too large.'):
    out = bytearray()
    _stream(url, source, cap=cap, deadline=deadline, sink=out.extend, cap_message=cap_message)
    return bytes(out)


def _json(url, source, *, cap=MAX_SEARCH_BYTES, deadline=None):
    data = _bytes(url, source, cap=cap, deadline=_now() + 30 if deadline is None else deadline)
    return json.loads(data.decode('utf-8'))


def _cached(key, load):
    now = _now()
    with _CACHE_LOCK:
        hit = _SEARCH.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = load()
    with _CACHE_LOCK:
        for stale in [k for k, (expires, _) in _SEARCH.items() if expires <= now]:
            del _SEARCH[stale]
        if len(_SEARCH) >= 64:
            _SEARCH.pop(next(iter(_SEARCH)))
        _SEARCH[key] = (now + SEARCH_TTL_S, value)
    return value


# --- search ------------------------------------------------------------------

def _thumb_route(source, source_id):
    return f'api/house/materials/sources/{source}/{source_id}/thumb'


def _polyhaven_assets():
    def load():
        data = _json(POLYHAVEN_ASSETS, 'polyhaven')
        if not isinstance(data, dict):
            raise ValueError('Unexpected Poly Haven answer.')
        return data
    return _cached(('polyhaven',), load)


def _polyhaven_resolutions(asset):
    largest = asset.get('max_resolution')
    try:
        side = max(int(v) for v in largest)
    except (TypeError, ValueError):
        return list(RESOLUTIONS)
    return [r for r in RESOLUTIONS if int(r[0]) * 1024 <= side]


def _polyhaven_search(query, category):
    words = query.lower().split()
    rows = []
    for slug, asset in _polyhaven_assets().items():
        if not isinstance(asset, dict) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', str(slug)):
            continue
        categories = [str(c).lower() for c in asset.get('categories') or []]
        if category and category.lower() not in categories:
            continue
        haystack = ' '.join([slug, str(asset.get('name', ''))] + [str(t) for t in asset.get('tags') or []]
                            + categories).lower()
        if not all(word in haystack for word in words):
            continue
        if isinstance(asset.get('thumbnail_url'), str):
            with _CACHE_LOCK:
                _THUMB_URLS[('polyhaven', slug)] = asset['thumbnail_url']
        rows.append((-(asset.get('download_count') or 0), dict(
            source='polyhaven', source_id=slug, name=str(asset.get('name') or slug),
            thumbnail=_thumb_route('polyhaven', slug), resolutions=_polyhaven_resolutions(asset),
            source_url=POLYHAVEN_PAGE.format(id=slug))))
    rows.sort(key=lambda pair: (pair[0], pair[1]['name']))
    return [row for _, row in rows[:MAX_RESULTS]]


def _acg_downloads(asset):
    out = []
    for folder in (asset.get('downloadFolders') or {}).values():
        categories = (folder or {}).get('downloadFiletypeCategories') or {}
        out += ((categories.get('zip') or {}).get('downloads') or [])
    return [d for d in out if isinstance(d, dict)]


def _acg_download(asset, resolution):
    """The zip for `resolution`: JPG first (a fraction of PNG's size), within the file cap."""
    downloads = _acg_downloads(asset)
    for kind in ('JPG', 'PNG'):
        for entry in downloads:
            size = entry.get('size')
            if (entry.get('attribute') == f'{resolution.upper()}-{kind}'
                    and (type(size) is not int or size <= MAX_FILE_BYTES)):
                return entry
    return None


def _acg_search(query, category):
    def load():
        data = _json(AMBIENTCG_SEARCH.format(q=quote(query.strip(), safe='')), 'ambientcg')
        assets = data.get('foundAssets') if isinstance(data, dict) else None
        if not isinstance(assets, list):
            raise ValueError('Unexpected ambientCG answer.')
        return assets
    rows = []
    for asset in _cached(('ambientcg', query.strip().lower()), load):
        sid = asset.get('assetId') if isinstance(asset, dict) else None
        if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,99}', sid):
            continue
        categories = [str(c).lower() for c in (asset.get('displayCategory'), asset.get('category')) if c]
        if category and category.lower() not in categories:
            continue
        preview = asset.get('previewImage') or {}
        if isinstance(preview, dict) and isinstance(preview.get('256-PNG'), str):
            with _CACHE_LOCK:
                _THUMB_URLS[('ambientcg', sid)] = preview['256-PNG']
        rows.append(dict(source='ambientcg', source_id=sid,
                         name=str(asset.get('customDisplayName') or asset.get('displayName') or sid),
                         thumbnail=_thumb_route('ambientcg', sid),
                         resolutions=[r for r in RESOLUTIONS if _acg_download(asset, r)],
                         source_url=AMBIENTCG_PAGE.format(id=sid)))
    return rows[:MAX_RESULTS]


def search(source: str, query: str = '', category: str | None = None) -> list:
    """[{source, source_id, name, thumbnail, resolutions, source_url}]; cached 10 minutes.
    `thumbnail` is this server's own proxy route, relative for ingress."""
    _source(source)
    query = (query or '')[:200]
    category = (category or '').strip() or None
    try:
        return _polyhaven_search(query, category) if source == 'polyhaven' else _acg_search(query, category)
    except Exception as exc:
        log.info('material source search %s failed: %s', source, exc)
        raise Unreachable(UNREACHABLE) from exc


def thumbnail(source: str, source_id: str) -> bytes:
    """A PNG at most 256 px, cached on disk under material_sources/thumbs."""
    _source(source)
    _source_id(source_id)
    path = thumbs_root() / f'{source}-{source_id}.png'
    if path.is_file():
        return path.read_bytes()
    with _CACHE_LOCK:
        url = _THUMB_URLS.get((source, source_id))
    url = url or (POLYHAVEN_THUMB if source == 'polyhaven' else AMBIENTCG_THUMB).format(id=source_id)
    try:
        from PIL import Image
        data = _bytes(url, source, cap=MAX_THUMB_BYTES, deadline=_now() + 20)
        with Image.open(io.BytesIO(data)) as picture:
            if picture.width * picture.height > 4096 * 4096:
                raise ValueError('Thumbnail too large.')
            picture.thumbnail((THUMB_SIDE, THUMB_SIDE))
            out = io.BytesIO()
            picture.convert('RGBA' if 'A' in picture.getbands() else 'RGB').save(out, format='PNG')
    except Exception as exc:
        log.info('material source thumbnail %s/%s failed: %s', source, source_id, exc)
        raise Unreachable(UNREACHABLE) from exc
    encoded = out.getvalue()
    twin_materials._atomic(path, encoded)
    return encoded


# --- jobs --------------------------------------------------------------------

def start_download(source: str, source_id: str, resolution: str, actor) -> str:
    _source(source)
    _source_id(source_id)
    if resolution not in RESOLUTIONS:
        raise ValueError('Choose a resolution of 1k, 2k or 4k.')
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        finished = [k for k, j in _JOBS.items() if j['state'] in ('done', 'failed')]
        for key in finished[:max(0, len(_JOBS) - MAX_JOBS_KEPT + 1)]:
            del _JOBS[key]
        _JOBS[job_id] = dict(id=job_id, state='queued', progress=0.0, source=source,
                             source_id=source_id, resolution=resolution)
    _QUEUE.put((job_id, source, source_id, resolution, actor))
    _ensure_worker()
    return job_id


def job(job_id: str) -> dict:
    """{state: queued|running|done|failed, progress: 0..1, material_id?, error?}"""
    with _JOBS_LOCK:
        if job_id not in _JOBS:
            raise KeyError(job_id)
        return dict(_JOBS[job_id])


def _set(job_id, **fields):
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(fields)


def _ensure_worker():
    global _WORKER
    with _JOBS_LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _WORKER = threading.Thread(target=_work, name='material-downloads', daemon=True)
            _WORKER.start()


def _work():
    while True:
        job_id, source, source_id, resolution, actor = _QUEUE.get()
        _set(job_id, state='running')
        try:
            material_id = _run(job_id, source, source_id, resolution, actor)
        except Exception as exc:
            _set(job_id, state='failed', error=_message(exc))
            log.info('material download %s %s %s failed: %r', source, source_id, resolution, exc)
        else:
            _set(job_id, state='done', progress=1.0, material_id=material_id)
            if on_published:
                try:
                    on_published()
                except Exception:
                    log.exception('material download publish signal failed')
        finally:
            _QUEUE.task_done()


def _message(exc):
    if isinstance(exc, HTTPError) and exc.code == 404:
        return 'That material is no longer available online.'
    if isinstance(exc, (zipfile.BadZipFile, zlib.error, EOFError)):
        return 'The archive is damaged.'
    if isinstance(exc, ValueError):
        return str(exc)
    if isinstance(exc, OSError):
        return UNREACHABLE
    return 'The download failed.'


class _Budget:
    """One job's bytes, deadline and progress."""

    def __init__(self, job_id):
        self.job_id = job_id
        self.deadline = _now() + DEADLINE_S
        self.read = 0
        self.expected = 0

    def count(self, n):
        self.read += n
        if self.read > MAX_JOB_BYTES:
            raise DownloadError(f'The download is larger than {_mb(MAX_JOB_BYTES)} in all.')
        if self.expected:
            _set(self.job_id, progress=round(min(.9, .9 * self.read / self.expected), 3))

    def fetch(self, url, source, target: Path):
        with target.open('wb') as out:
            _stream(url, source, cap=MAX_FILE_BYTES, deadline=self.deadline, sink=out.write,
                    cap_message=f'A file is larger than {_mb(MAX_FILE_BYTES)}.', on_bytes=self.count)

    def json(self, url, source):
        return _json(url, source, cap=MAX_FILE_BYTES, deadline=self.deadline)


def _tile(width, height, unit):
    try:
        tile = [round(float(width) / unit, 3), round(float(height) / unit, 3)]
    except (TypeError, ValueError):
        return None
    return tile if all(.25 <= axis <= 200 for axis in tile) else None


def _run(job_id, source, source_id, resolution, actor):
    budget = _Budget(job_id)
    material_id = twin_materials.new_id()
    stage = staging_root() / job_id
    try:
        stage.mkdir(parents=True)
        plan = (_polyhaven if source == 'polyhaven' else _ambientcg)(source_id, resolution, budget, stage)
        fields, images, convention = plan
        maps = {}
        for slot, path in images:  # staged files, decoded one at a time
            if _now() > budget.deadline:
                raise DownloadError('The download took longer than 3 minutes.')
            maps[slot] = twin_materials.ingest_image(material_id, slot, path.read_bytes(), staged=True)
        if 'base_color' not in maps:
            raise DownloadError('That material has no colour map.')
        fields['maps'] = maps
        fields.setdefault('params', {})['normal_convention'] = convention
        record = twin_materials.create(fields, actor, material_id=material_id, source=source)
        return record['id']
    except BaseException:
        folder = twin_materials.root() / material_id
        if not (folder / 'material.json').exists():
            shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _slot(table, token):
    value = table.get(token.lower())
    if value is None:
        return None, None
    return value if isinstance(value, tuple) else (value, None)


def _polyhaven(slug, resolution, budget, stage):
    files = budget.json(POLYHAVEN_FILES.format(id=slug), 'polyhaven')
    if not isinstance(files, dict):
        raise DownloadError('That material is no longer available online.')
    with _CACHE_LOCK:
        cached = _SEARCH.get(('polyhaven',))
    asset = (cached[1] if cached else {}).get(slug)
    if not isinstance(asset, dict):
        try:
            asset = budget.json(POLYHAVEN_INFO.format(id=slug), 'polyhaven')
        except DownloadError:
            raise
        except Exception:
            asset = {}
    picks = {}  # slot -> (url, convention, size)
    for key, by_res in files.items():
        if not isinstance(by_res, dict) or not isinstance(by_res.get(resolution), dict):
            continue
        by_fmt = by_res[resolution]
        slot, convention = _slot(POLYHAVEN_SLOTS, key)
        if slot is None:
            url = next((e.get('url') for e in by_fmt.values() if isinstance(e, dict)), '') or ''
            token = re.search(r'_([a-z_]+)_\d+k\.[a-z]+$', url.lower())
            slot, convention = _slot(POLYHAVEN_SLOTS, token.group(1)) if token else (None, None)
        if slot is None:
            continue
        # Colour as JPEG; data maps as PNG while ingest can take it, else JPEG.
        order = ('jpg', 'png') if slot == 'base_color' else ('png', 'jpg')
        choice = None
        for fmt in order:
            entry = by_fmt.get(fmt)
            if not isinstance(entry, dict) or not isinstance(entry.get('url'), str):
                continue
            size = entry.get('size')
            if fmt == 'png' and slot != 'base_color' and type(size) is int and size > twin_materials.MAX_INPUT_BYTES:
                continue
            choice = (entry['url'], convention, size if type(size) is int else 0)
            break
        if choice is None:
            continue
        if slot == 'normal' and slot in picks and picks[slot][1] == 'gl':
            continue  # GL wins over DX
        picks[slot] = choice
    if 'base_color' not in picks:
        raise DownloadError('That resolution is not available for this material.')
    for url, _, size in picks.values():
        if size > MAX_FILE_BYTES:
            raise DownloadError(f'A file is larger than {_mb(MAX_FILE_BYTES)}.')
    budget.expected = sum(size for _, _, size in picks.values())
    if budget.expected > MAX_JOB_BYTES:
        raise DownloadError(f'The download is larger than {_mb(MAX_JOB_BYTES)} in all.')
    images = []
    for index, (slot, (url, _, _)) in enumerate(sorted(picks.items())):
        target = stage / f'{index}.img'
        budget.fetch(url, 'polyhaven', target)
        images.append((slot, target))
    params = {}
    dimensions = asset.get('dimensions') if isinstance(asset, dict) else None
    if isinstance(dimensions, list) and len(dimensions) >= 2:
        tile = _tile(dimensions[0], dimensions[1], 304.8)  # millimetres
        if tile:
            params['tile_ft'] = tile
    name = str((asset or {}).get('name') or slug.replace('_', ' ').title())[:120]
    fields = dict(name=name, licence='CC0', source_url=POLYHAVEN_PAGE.format(id=slug), params=params)
    return fields, images, picks['normal'][1] if 'normal' in picks else 'gl'


def _unsafe(name):
    if not name or name.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', name) or '\0' in name:
        return True
    return any(part == '..' for part in re.split(r'[\\/]', name))


def _ambientcg(asset_id, resolution, budget, stage):
    data = budget.json(AMBIENTCG_ASSET.format(id=quote(asset_id, safe='')), 'ambientcg')
    assets = data.get('foundAssets') if isinstance(data, dict) else None
    asset = next((a for a in assets or [] if isinstance(a, dict) and a.get('assetId') == asset_id), None)
    if asset is None:
        raise DownloadError('That material is no longer available online.')
    download = _acg_download(asset, resolution)
    url = download and (download.get('downloadLink') or download.get('fullDownloadPath'))
    if not isinstance(url, str):
        raise DownloadError('That resolution is not available for this material.')
    budget.expected = download.get('size') if type(download.get('size')) is int else 0
    archive_path = stage / 'archive.zip'
    budget.fetch(url, 'ambientcg', archive_path)
    images, conventions = [], {}
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_ENTRIES:
            raise DownloadError(f'The archive has too many entries (over {MAX_ARCHIVE_ENTRIES}).')
        if any(_unsafe(entry.filename) for entry in entries):
            raise DownloadError('The archive contains unsafe paths.')
        if sum(entry.file_size for entry in entries) > MAX_ARCHIVE_EXPANDED:
            raise DownloadError(f'The archive is too large when expanded (over {_mb(MAX_ARCHIVE_EXPANDED)}).')
        picks = {}
        for entry in entries:
            if entry.is_dir():
                continue
            name = PurePosixPath(entry.filename.replace('\\', '/')).name
            stem, dot, suffix = name.rpartition('.')
            if not dot or '.' + suffix.lower() not in IMAGE_SUFFIXES or '_' not in stem:
                continue
            slot, convention = _slot(AMBIENTCG_SLOTS, stem.rsplit('_', 1)[1])
            if slot is None or (slot == 'normal' and picks.get('normal', (None, None))[1] == 'gl'):
                continue
            picks[slot] = (entry, convention)
        expanded = 0
        for slot, (entry, convention) in sorted(picks.items(), key=lambda kv: kv[0]):
            if entry.file_size > MAX_FILE_BYTES:
                raise DownloadError(f'A file is larger than {_mb(MAX_FILE_BYTES)}.')
            target, written = stage / f'{slot}.img', 0
            # Only mapped entries are extracted, to a name we chose, never the entry's path.
            with archive.open(entry) as stream, target.open('wb') as out:
                while True:
                    chunk = stream.read(CHUNK)
                    if not chunk:
                        break
                    expanded += len(chunk)
                    written += len(chunk)
                    if expanded > MAX_ARCHIVE_EXPANDED:
                        raise DownloadError(
                            f'The archive is too large when expanded (over {_mb(MAX_ARCHIVE_EXPANDED)}).')
                    if written > MAX_FILE_BYTES:
                        raise DownloadError(f'A file is larger than {_mb(MAX_FILE_BYTES)}.')
                    if _now() > budget.deadline:
                        raise DownloadError('The download took longer than 3 minutes.')
                    out.write(chunk)
            images.append((slot, target))
            conventions[slot] = convention
    params = {}
    tile = _tile(asset.get('dimensionX'), asset.get('dimensionY'), 30.48)  # centimetres
    if tile:
        params['tile_ft'] = tile
    name = str(asset.get('customDisplayName') or asset.get('displayName') or asset_id)[:120]
    fields = dict(name=name, licence='CC0', source_url=AMBIENTCG_PAGE.format(id=asset_id), params=params)
    return fields, images, conventions.get('normal') or 'gl'
