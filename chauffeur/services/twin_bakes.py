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

from services import twin_store

MAX_PAGE_BYTES = 16 * 1024 * 1024
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
KTX2_SIGNATURE = b'\xabKTX 20\xbb\r\n\x1a\n'
_KEY = re.compile(r'[0-9a-f]{16,64}')
_LOCK = threading.RLock()


def check_key(key):
    if not isinstance(key, str) or not _KEY.fullmatch(key):
        raise ValueError('Invalid bake key.')
    return key


def check_page(page):
    if not re.fullmatch(r'[0-9]+', str(page)):
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


def save_manifest(key, body):
    path = _directory(key) / 'manifest.json'
    _check_manifest(body)
    data = json.dumps(body, allow_nan=False).encode('utf-8')
    with _LOCK:
        _write(path, data)
    return body


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
