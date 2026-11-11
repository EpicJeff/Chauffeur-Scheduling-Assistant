"""Atomic storage for the twin's baked light pages and manifests."""
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

from services import twin_store

MAX_PAGE_BYTES = 16 * 1024 * 1024
MAX_PAGES = 64                      # page index 0..63 (M7)
MAX_MANIFEST_BYTES = 1024 * 1024    # 1 MiB (M7)
LEASE_SECONDS = 60                  # Ruling B17
KEEP_RECENT_SECONDS = 600           # a key written this recently is a bake in progress
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
KTX2_SIGNATURE = b'\xabKTX 20\xbb\r\n\x1a\n'
_KEY = re.compile(r'[0-9a-f]{16,64}')
_LOCK = threading.RLock()
_LEASES = {}                        # key -> (owner, until); the add-on runs one worker
_OWNER = re.compile(r'[A-Za-z0-9_.:-]{1,64}')


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


def save_page(key, page, data):
    path = _directory(key) / f'{check_page(page)}.png'
    if len(data) > MAX_PAGE_BYTES:
        raise ValueError('Bake page exceeds 16 MiB.')
    if not data.startswith((PNG_SIGNATURE, KTX2_SIGNATURE)):
        raise ValueError('Bake page must be a PNG or KTX2.')
    with _LOCK:
        _write(path, data)
    return _etag(data)


def read_page(key, page):
    path = _directory(key) / f'{check_page(page)}.png'
    # Windows refuses a replace while a reader has the destination open.
    # Return bytes so no file handle survives the lock or the response.
    with _LOCK:
        data = path.read_bytes()
    return data, _etag(data)


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
    for entry in [body.get('sky'), *lights.values()]:
        if not isinstance(entry, dict):
            raise ValueError('Bake entries need a page and channel.')
        page, channel = entry.get('page'), entry.get('channel')
        if type(page) is not int or not 0 <= page < pages:
            raise ValueError('Bake entry page is outside the manifest.')
        if type(channel) is not int or not 0 <= channel <= 3:
            raise ValueError('Bake channel must be between 0 and 3.')
    for entry in lights.values():
        check_key(entry.get('key'))
    # Old PNG manifests remain readable and writable during the transition.
    if 'formats' in body:
        formats = body['formats']
        if not isinstance(formats, list) or len(formats) != pages or any(f not in ('png', 'ktx2') for f in formats):
            raise ValueError('Bake formats must describe every page as png or ktx2.')
    if 'densities' in body:
        densities = body['densities']
        if not isinstance(densities, dict) or any(
            type(densities.get(k)) not in (int, float) or not math.isfinite(densities[k]) or densities[k] <= 0
            for k in ('sky', 'room')
        ):
            raise ValueError('Bake densities need positive finite sky and room values.')
    # Which model round the desk baked, and whether every light and the sky are done
    # (Ruling B15: the editor says when lights wait to re-bake).
    if body.get('round') is not None and (type(body['round']) is not int or body['round'] < 0):
        raise ValueError('Bake round must be a round id.')
    if 'complete' in body and type(body['complete']) is not bool:
        raise ValueError('Bake complete must be true or false.')


def save_manifest(key, body):
    path = _directory(key) / 'manifest.json'
    _check_manifest(body)
    data = json.dumps(body, allow_nan=False).encode('utf-8')
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError('Bake manifest exceeds 1 MiB.')
    with _LOCK:
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


def status(current_round):
    """{'waiting': bool} from the most recently saved manifest that names its round,
    or None when no desk has recorded a bake (Ruling B15)."""
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
        root = Path(twin_store.DATA_DIR) / 'bakes'
        if not root.is_dir():
            return
        for path in root.iterdir():
            if path.name not in live_keys and path.is_dir():
                if path.is_symlink():
                    path.unlink()
                else:
                    shutil.rmtree(path)
