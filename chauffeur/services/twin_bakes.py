"""Atomic storage for the twin's baked light pages, grid chunks and manifests."""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time
import zlib

from services import twin_store

MAX_PAGE_BYTES = 16 * 1024 * 1024
MAX_GRID_BYTES = 8 * 1024 * 1024
MAX_GRID_EXPANDED_BYTES = 64 * 1024 * 1024
MAX_ATLAS_BYTES = 64 * 1024 * 1024
KEEP_ATLASES = 2
MAX_PAGES = 64                      # page index 0..63 (M7)
MAX_MANIFEST_BYTES = 1024 * 1024    # 1 MiB (M7)
LEASE_SECONDS = 60                  # Ruling B17
KEEP_RECENT_SECONDS = 600           # a key written this recently is a bake in progress
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
KTX2_SIGNATURE = b'\xabKTX 20\xbb\r\n\x1a\n'
GRID_SIGNATURE = b'MVG1'
_KEY = re.compile(r'[0-9a-f]{16,64}')
_GRID_NAME = re.compile(r'[0-9a-f]{16,64}')
_LOCK = threading.RLock()
_LEASES = {}                        # key -> (owner, until); the add-on runs one worker
_OWNER = re.compile(r'[A-Za-z0-9_.:-]{1,64}')
_PAGE_VERSIONS = {}


def _now():
    return time.time()


def check_key(key):
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError('Invalid bake key.')
    return key


def check_page(page):
    if not re.fullmatch(r'[0-9]+', str(page)) or int(page) >= MAX_PAGES:
        raise ValueError('Invalid bake page.')
    return int(page)


def check_grid_name(name):
    if not isinstance(name, str) or not _GRID_NAME.fullmatch(name):
        raise ValueError('Invalid bake grid name.')
    return name


def _directory(key):
    return Path(twin_store.DATA_DIR) / 'bakes' / check_key(key)


def _etag(data):
    return '"' + hashlib.sha256(data).hexdigest() + '"'


def _write(path, data):
    """Caller holds _LOCK through creation, replacement and cleanup."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.', suffix='.tmp',
                                         delete=False) as out:
            temp_path = out.name
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and os.path.exists(temp_path):
            os.unlink(temp_path)


class BakeLeaseConflict(Exception):
    """A different desk owns the live lease; no bake bytes may be changed."""


def _write_lease(key, owner):
    """Caller holds _LOCK through this check and the write (including pruning)."""
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        raise ValueError('A bake write needs a lease owner.')
    now = _now()
    held = _LEASES.get(key)
    if held and held[1] > now and held[0] != owner:
        raise BakeLeaseConflict('Another desk holds the bake lease.')
    # An expired, unclaimed lease can safely continue. A write also renews an
    # owner's live lease, so the next desk cannot enter during publication.
    _LEASES[key] = (owner, now + LEASE_SECONDS)


def save_page(key, page, data, owner, info=False):
    path = _directory(key) / f'{check_page(page)}.png'
    if len(data) > MAX_PAGE_BYTES:
        raise ValueError('Bake page exceeds 16 MiB.')
    if not data.startswith((PNG_SIGNATURE, KTX2_SIGNATURE)):
        raise ValueError('Bake page must be a PNG or KTX2.')
    with _LOCK:
        _write_lease(key, owner)
        _write(path, data)
        stat = path.stat()
        # Nanoseconds exceed JavaScript's safe integer range. Persist strings
        # through the upload answer and manifest without rounding the stamp.
        version = {'stat': [str(stat.st_size), str(stat.st_mtime_ns), str(stat.st_ctime_ns)], 'etag': _etag(data)}
        if len(_PAGE_VERSIONS) >= 256:
            _PAGE_VERSIONS.clear()
        _PAGE_VERSIONS[path] = version
        return {'etag': version['etag'], 'version': version['stat']} if info else version['etag']


def _check_grid_body(data):
    """Accept raw MVG1 bytes, or gzip whose expanded bytes start with MVG1."""
    bad = 'Bake grid must be MVG1 bytes or gzip of MVG1 bytes.'
    if data.startswith(GRID_SIGNATURE):
        return
    if not data.startswith(b'\x1f\x8b'):
        raise ValueError(bad)
    inflater = zlib.decompressobj(wbits=31)
    head = b''
    total = 0
    try:
        pending = data
        step = 1024 * 1024
        while not inflater.eof:
            out = inflater.decompress(pending, step)
            if not out and not inflater.unconsumed_tail:
                break
            total += len(out)
            if total > MAX_GRID_EXPANDED_BYTES:
                raise ValueError('Bake grid expands beyond 64 MiB.')
            if len(head) < len(GRID_SIGNATURE):
                head += out[:len(GRID_SIGNATURE) - len(head)]
            pending = inflater.unconsumed_tail
        if not inflater.eof:
            raise ValueError('Bake grid gzip is truncated.')
    except zlib.error:
        raise ValueError('Bake grid gzip is corrupt.') from None
    if head != GRID_SIGNATURE:
        raise ValueError(bad)


def save_grid(key, name, data, owner):
    path = _directory(key) / f'grid-{check_grid_name(name)}.bin'
    if len(data) > MAX_GRID_BYTES:
        raise ValueError('Bake grid exceeds 8 MiB.')
    _check_grid_body(data)
    with _LOCK:
        _write_lease(key, owner)
        _write(path, data)
        stat = path.stat()
        return {'etag': _etag(data),
                'version': [str(stat.st_size), str(stat.st_mtime_ns), str(stat.st_ctime_ns)]}


def grid_response(key, name, matches=()):
    path = _directory(key) / f'grid-{check_grid_name(name)}.bin'
    # Read and hash under the same publication lock as writes. No file handle
    # survives the lock (Windows), and the content ETag survives server restarts.
    with _LOCK:
        data = path.read_bytes()
        etag = _etag(data)
        hit = any(tag.strip().removeprefix('W/') in (etag, '*') for tag in matches)
        return None if hit else data, etag, len(data)


def _page_stat(path):
    stat = path.stat()
    stamp = [str(stat.st_size), str(stat.st_mtime_ns), str(stat.st_ctime_ns)]
    version = _PAGE_VERSIONS.get(path)
    if version is None:
        try:
            manifest = json.loads((path.parent / 'manifest.json').read_text(encoding='utf-8'))
            saved = manifest.get('pageIntegrity', {}).get(path.stem, {})
            version = {'stat': saved.get('version'), 'etag': saved.get('digest')}
        except (FileNotFoundError, ValueError, AttributeError, TypeError):
            version = {}
        if not isinstance(version, dict):
            version = {}
        if len(_PAGE_VERSIONS) >= 256:
            _PAGE_VERSIONS.clear()
        _PAGE_VERSIONS[path] = version
    # Identical re-uploads retain their content ETag. A changed file cannot use
    # the saved digest: return its stat identity without reading page bytes.
    etag = version.get('etag') if version.get('stat') == stamp else None
    return etag or f'"{stat.st_size:x}-{stat.st_mtime_ns:x}-{stat.st_ctime_ns:x}"', stat.st_size


def page_response(key, page, matches=()):
    """Answer conditional metadata from stat; read bytes only for a 200.

    Keep stat, comparison and reading under the publication lock so the ETag
    always describes this response, including concurrent Windows replacements.
    """
    path = _directory(key) / f'{check_page(page)}.png'
    with _LOCK:
        etag, size = _page_stat(path)
        hit = any(tag.strip().removeprefix('W/') in (etag, '*') for tag in matches)
        return None if hit else path.read_bytes(), etag, size


def read_page(key, page):
    path = _directory(key) / f'{check_page(page)}.png'
    # Windows refuses a replace while a reader has the destination open.
    # Return bytes so no file handle survives the lock or the response.
    with _LOCK:
        data = path.read_bytes()
    return data, _etag(data)


def save_atlas(key, data):
    """Opaque binary transport, addressed by the worker INPUT fingerprint."""
    path = Path(twin_store.DATA_DIR) / 'atlases' / check_key(key)
    if len(data) > MAX_ATLAS_BYTES:
        raise ValueError('Atlas exceeds 64 MiB.')
    with _LOCK:
        _write(path, data)
        _prune_atlases(current=key)
    return _etag(data)


def read_atlas(key):
    path = Path(twin_store.DATA_DIR) / 'atlases' / check_key(key)
    with _LOCK:
        return path.read_bytes()


def _prune_atlases(current=None):
    # Input keys differ from bake output keys; retain by upload time, not live_keys.
    root = Path(twin_store.DATA_DIR) / 'atlases'
    if not root.is_dir():
        return
    paths = [p for p in root.iterdir() if _KEY.fullmatch(p.name) and p.is_file() and not p.is_symlink()]
    # Keep the just-written input even if the system clock moved backwards.
    paths.sort(key=lambda p: (p.name == current, p.stat().st_mtime_ns), reverse=True)
    for path in paths[KEEP_ATLASES:]:
        path.unlink()


def _check_manifest(body):
    if not isinstance(body, dict):
        raise ValueError('Bake manifest must be an object.')
    pages = body.get('pages')
    if type(pages) is not int or pages < 1:
        raise ValueError('Bake manifest needs at least one page.')
    if pages > MAX_PAGES:
        raise ValueError(f'Bake manifest has more than {MAX_PAGES} pages.')
    lights = body.get('lights')
    if not isinstance(lights, dict):
        raise ValueError('Bake lights must be an object.')
    for entry in lights.values():
        if not isinstance(entry, dict):
            raise ValueError('Bake entries need a page and channel.')
        page, channel = entry.get('page'), entry.get('channel')
        if type(page) is not int or not 0 <= page < pages:
            raise ValueError('Bake entry page is outside the manifest.')
        if type(channel) is not int or not 0 <= channel <= 3:
            raise ValueError('Bake channel must be between 0 and 3.')
        if 'pages' in entry:
            reached = entry['pages']
            if (not isinstance(reached, list) or not reached or
                    any(type(p) is not int or not 0 <= p < pages for p in reached) or
                    len(set(reached)) != len(reached) or page != reached[0]):
                raise ValueError('Bake reach pages must be unique, in range, and start with page.')
    for entry in lights.values():
        check_key(entry.get('key'))
        if 'cheap' in entry:
            check_key(entry['cheap'])
        if 'grid' in entry:
            check_grid_name(entry['grid'])
        if 'gridLayout' in entry:
            check_key(entry['gridLayout'])
    # Force intent and completed-light receipts survive reloads. Bounded tokens
    # keep the existing manifest byte cap and legacy manifests unchanged.
    for value in [body, *lights.values()]:
        if 'forceRound' in value and (not isinstance(value['forceRound'], str) or
                                      not _OWNER.fullmatch(value['forceRound'])):
            raise ValueError('Bake force round must be a bounded round token.')
    # Old PNG manifests remain readable and writable during the transition.
    if 'formats' in body:
        formats = body['formats']
        if not isinstance(formats, list) or len(formats) != pages or any(f not in ('png', 'ktx2') for f in formats):
            raise ValueError('Bake formats must describe every page as png or ktx2.')
    if 'densities' in body:
        densities = body['densities']
        if not isinstance(densities, dict) or any(
            type(densities.get(k)) not in (int, float) or not math.isfinite(densities[k]) or densities[k] <= 0
            for k in ('room',)
        ):
            raise ValueError('Bake densities need a positive finite room value.')
    # Which model round the desk baked, and whether every room light is done
    # (Ruling B15: the editor says when lights wait to re-bake).
    if body.get('round') is not None and (type(body['round']) is not int or body['round'] < 0):
        raise ValueError('Bake round must be a round id.')
    if 'complete' in body and type(body['complete']) is not bool:
        raise ValueError('Bake complete must be true or false.')
    if 'pageIntegrity' in body:
        integrity = body['pageIntegrity']
        if not isinstance(integrity, dict):
            raise ValueError('Invalid lightmap page integrity.')
        for page, value in integrity.items():
            if (not re.fullmatch(r'[0-9]+', str(page)) or int(page) >= pages
                    or not isinstance(value, dict) or type(value.get('size')) is not int
                    or not 0 < value['size'] <= MAX_PAGE_BYTES
                    or not isinstance(value.get('digest'), str) or not re.fullmatch(r'"[0-9a-f]{64}"', value['digest'])
                    or ('version' in value and (not isinstance(value['version'], list)
                        or len(value['version']) != 3 or any(not isinstance(n, str) or not re.fullmatch(r'[0-9]{1,32}', n) for n in value['version'])))):
                raise ValueError('Invalid lightmap page integrity.')


def save_manifest(key, body, owner):
    path = _directory(key) / 'manifest.json'
    _check_manifest(body)
    data = json.dumps(body, allow_nan=False).encode('utf-8')
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError('Bake manifest exceeds 1 MiB.')
    with _LOCK:
        _write_lease(key, owner)
        _write(path, data)
        _prune_older(key)
    return body


def _touched(path):
    manifest = path / 'manifest.json'
    times = [path.stat().st_mtime]
    if manifest.exists():
        times.append(manifest.stat().st_mtime)
    return max(times)


def _prune_older(current):
    """Keep the key just saved and the most recent other one (I3). A key written in
    the last few minutes is a bake in progress on some desk and is kept too."""
    _prune_atlases()
    root = Path(twin_store.DATA_DIR) / 'bakes'
    others = []
    for path in root.iterdir():
        if path.name == current or not path.is_dir() or path.is_symlink() or not _KEY.fullmatch(path.name):
            continue
        try:
            others.append((_touched(path), path))
        except OSError:
            continue
    others.sort(key=lambda row: row[0], reverse=True)
    now = _now()
    for when, path in others[1:]:
        if now - when < KEEP_RECENT_SECONDS:
            continue
        shutil.rmtree(path, ignore_errors=True)


def latest_manifest():
    """Small editor metadata read; never generates an atlas or opens page bytes."""
    root = Path(twin_store.DATA_DIR) / 'bakes'
    with _LOCK:
        if not root.is_dir():
            return None
        latest = None
        for path in root.iterdir():
            manifest = path / 'manifest.json'
            if not _KEY.fullmatch(path.name) or not manifest.is_file():
                continue
            try:
                when = manifest.stat().st_mtime
            except OSError:
                continue
            if latest is None or when > latest[0]:
                latest = (when, manifest)
        if latest is None:
            return None
        try:
            body = json.loads(latest[1].read_bytes())
        except (OSError, ValueError):
            return None
    return {'key': latest[1].parent.name, 'manifest': body}


def status(current_round):
    """Legacy editor-poll summary, kept for callers of the shared snapshot."""
    latest = latest_manifest()
    body = latest['manifest'] if latest else {}
    if body.get('round') is None:
        return None
    return {'waiting': body['round'] != current_round or body.get('complete') is not True}


def lease(key, owner, action):
    """Ruling B17: one desk bakes a key at a time. Answers (ok, body)."""
    check_key(key)
    if not isinstance(owner, str) or not _OWNER.fullmatch(owner):
        raise ValueError('A lease needs an owner.')
    if action not in ('acquire', 'release', 'check'):
        raise ValueError('A lease action is acquire, release or check.')
    with _LOCK:
        now = _now()
        held = _LEASES.get(key)
        if held and held[1] <= now:
            _LEASES.pop(key, None)
            held = None
        if action == 'check':
            return True, {'free': held is None or held[0] == owner}
        if action == 'release':
            if held and held[0] == owner:
                _LEASES.pop(key, None)
            return True, {'held': False}
        if held and held[0] != owner:
            return False, {'held': False, 'seconds': max(1, math.ceil(held[1] - now))}
        _LEASES[key] = (owner, now + LEASE_SECONDS)
        return True, {'held': True, 'seconds': LEASE_SECONDS}


def read_manifest(key):
    path = _directory(key) / 'manifest.json'
    with _LOCK:
        return json.loads(path.read_bytes())


def prune(live_keys):
    live_keys = set(live_keys)
    with _LOCK:
        _prune_atlases()
        root = Path(twin_store.DATA_DIR) / 'bakes'
        if not root.is_dir():
            return
        for path in root.iterdir():
            if path.name not in live_keys and path.is_dir():
                if path.is_symlink():
                    path.unlink()
                else:
                    shutil.rmtree(path)
