"""Vetted twin assets and style kits, with an atomic fetch-once disk cache."""
import json
import os
from pathlib import Path
import re
import shutil
import threading
import uuid
from urllib.request import Request, urlopen

from services import twin_objects

_ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.Lock()
_ASSET_LOCKS: dict[str, threading.Lock] = {}
_urlopen = urlopen
# The size range a placed item may take, as a factor of the asset's own size.
ITEM_SCALE = tuple(twin_objects.SCHEMA['common']['scale'][key] for key in ('min', 'max'))


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


def material_choices(kit_id='modern_farmhouse'):
    """The Library's material list, from the existing kit and vetted manifest."""
    refs = kit(kit_id)['materials']
    words = lambda value: value.replace('_', ' ').strip().capitalize()
    choices = []
    for asset, entry in manifest().items():
        if entry.get('kind') == 'material':
            color = next((ref['color'] for ref in refs.values() if ref['asset'] == asset), '#b8b0a4')
            choices.append({'id': asset, 'name': words(asset), 'color': color})
    for ref in refs.values():
        choice = {'id': ref['asset'], 'name': words(ref['asset']), 'color': ref['color']}
        if choice not in choices:
            choices.append(choice)
    return choices


def material_slot_error(value):
    """A feature default (None), kit role, or vetted library material with optional tint."""
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get('id'), str) or not value['id']:
        return 'Choose a material with an id.'
    if set(value) - {'id', 'color'}:
        return 'A material slot accepts only id and optional color.'
    if 'color' in value and (not isinstance(value['color'], str) or not value['color'].strip()):
        return 'Choose a material with a non-empty color.'
    if value['id'] not in kit('modern_farmhouse')['materials'] and value['id'] not in {m['id'] for m in material_choices()}:
        return f"Unknown material id: {value['id']}. Choose a material from the Library."
    return None


def normalize_material_slot(value):
    """Return a detached canonical reference; reject unknown ids rather than guessing."""
    if error := material_slot_error(value):
        raise ValueError(error)
    return None if value is None else {key: value[key] for key in ('id', 'color') if key in value}


def ensure(asset_id: str) -> str:
    """Return the complete asset directory; failed downloads publish nothing."""
    from services import twin_store
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
