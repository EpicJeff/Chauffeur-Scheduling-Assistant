"""Vetted twin assets and style kits, with an atomic fetch-once disk cache."""
import json
import os
from pathlib import Path
import re
import shutil
import threading
import uuid
from urllib.request import Request, urlopen

from services import twin_store

_ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.Lock()
_ASSET_LOCKS: dict[str, threading.Lock] = {}
_urlopen = urlopen


def manifest() -> dict:
    with (_ROOT / 'twin_library' / 'manifest.json').open(encoding='utf-8') as file:
        return json.load(file)


def kit(kit_id: str) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_-]+', kit_id):
        raise KeyError(kit_id)
    try:
        with (_ROOT / 'twin_kits' / f'{kit_id}.json').open(encoding='utf-8') as file:
            return json.load(file)
    except FileNotFoundError as exc:
        raise KeyError(kit_id) from exc


def ensure(asset_id: str) -> str:
    """Return the complete asset directory; failed downloads publish nothing."""
    assets = manifest()
    asset = assets[asset_id]
    library = Path(twin_store.DATA_DIR) / 'library'
    target = library / asset_id
    # Published directories are complete (atomic rename below). Cached reads
    # never wait for an unrelated asset's download or even the lock registry.
    if target.is_dir():
        return str(target)
    with _LOCK:
        asset_lock = _ASSET_LOCKS.setdefault(asset_id, threading.Lock())
    # Sync routes run in worker threads: serialize only the same asset.
    with asset_lock:
        if target.is_dir():
            return str(target)
        try:
            library.mkdir(parents=True, exist_ok=True)
            staged = library / f'.{asset_id}-{uuid.uuid4().hex}.tmp'
            staged.mkdir()
            try:
                for name, url in asset['files'].items():
                    destination = Path(staged) / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    request = Request(url, headers={'User-Agent': 'Chauffeur-Twin/1.0'})
                    with _urlopen(request, timeout=15) as response:
                        destination.write_bytes(response.read())
                # Same-filesystem rename exposes all files together, including
                # the textures/ directory referenced by a model's glTF.
                os.rename(staged, target)
            finally:
                if staged.exists():
                    shutil.rmtree(staged)
        except Exception as exc:
            raise OSError(f'Unable to cache twin asset {asset_id}') from exc
    return str(target)
