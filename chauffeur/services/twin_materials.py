"""Household PBR assets. Material history is independent of house history.

Records publish atomically; maps are immutable and addressed by their encoded bytes.
Old maps remain available for source reset, material undo, and house/save references.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import threading
import uuid

from services import twin_library, twin_store

SLOTS = ('base_color', 'normal', 'roughness', 'metalness', 'ao', 'orm', 'height')
DEFAULT_PARAMS = dict(tint='#ffffff', roughness=1, metalness=1, normal_scale=1,
                      normal_convention='gl', ao_intensity=1, tile_ft=[4, 4],
                      rotation_deg=0, random_offset=False)
MAX_INPUT_BYTES = 40 * 1024 * 1024
MAX_FILES = 12
MAX_MATERIAL_BYTES = 200 * 1024 * 1024
MAX_SIDE = 4096
_GUARD = threading.Lock()
_LOCKS = {}


def root() -> Path:
    return Path(twin_store.DATA_DIR) / 'materials'


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('No such material.')
    return value


def _lock(mid):
    _id(mid)
    with _GUARD:
        return _LOCKS.setdefault(mid, threading.Lock())


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'.{path.name}-{uuid.uuid4().hex}.tmp')
    try:
        with temp.open('wb') as stream:
            stream.write(data)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _json(path, value):
    _atomic(path, json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8'))


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _bump():
    with _GUARD:
        path = root() / 'revision.json'
        revision = _read(path) if path.exists() else 0
        _json(path, revision + 1)


def _builtin_rows(kit_id='modern_farmhouse'):
    refs = twin_library.kit(kit_id)['materials']
    ids = [mid for mid, entry in twin_library.manifest().items() if entry['kind'] == 'material']
    ids += [ref['asset'] for ref in refs.values() if ref['asset'] not in ids]
    rows = []
    for mid in dict.fromkeys(ids):
        color = next((ref['color'] for ref in refs.values() if ref['asset'] == mid), '#b8b0a4')
        rows.append(dict(id=mid, name=mid.replace('_', ' ').capitalize(), source='builtin',
                         color=color, thumbnail_url=None, builtin=True, archived=False, revision=0))
    return rows


def _builtin(mid):
    row = next((r for r in _builtin_rows() if r['id'] == mid), None)
    if row is None:
        return None
    entry = twin_library.manifest().get(mid, {})
    params = deepcopy(DEFAULT_PARAMS)
    params['tint'] = row['color']
    maps = {}
    for filename in entry.get('files', {}):
        slot = next((s for suffix, s in (('_diff_', 'base_color'), ('_nor_gl_', 'normal'),
                                        ('_rough_', 'roughness'), ('_arm_', 'orm'), ('_ao_', 'ao'))
                     if suffix in filename), None)
        if slot:
            maps[slot] = filename
    return dict(id=mid, name=row['name'], source='builtin', licence=entry.get('licence'),
                source_url=entry.get('page'), based_on=None, revision=0, archived=False,
                created_by=None, updated_at=None, maps=maps, params=params, source_snapshot=None)


def get(material_id) -> dict:
    mid = _id(material_id)
    builtin = _builtin(mid)
    if builtin:
        return builtin
    try:
        return _read(root() / mid / 'material.json')
    except FileNotFoundError as exc:
        raise ValueError('No such material.') from exc


def _editable(mid):
    record = get(mid)
    if record['source'] == 'builtin':
        raise ValueError('Built-in materials are read-only. Duplicate this material first.')
    return record


def catalogue(include_archived=False) -> dict:
    rows = _builtin_rows()
    for path in sorted(root().glob('*/material.json')):
        try:
            record = _read(path)
        except FileNotFoundError:  # A concurrent unreferenced deletion.
            continue
        if record['archived'] and not include_archived:
            continue
        rows.append(dict(id=record['id'], name=record['name'], source=record['source'],
                         color=record['params']['tint'], thumbnail_url=None, builtin=False,
                         archived=record['archived'], revision=record['revision']))
    path = root() / 'revision.json'
    return {'revision': _read(path) if path.exists() else 0, 'materials': rows}


def page_manifest() -> dict:
    result = twin_library.manifest()
    for row in catalogue(True)['materials']:
        if row['builtin']:
            continue
        try:
            record = get(row['id'])
        except ValueError:
            continue
        result[row['id']] = dict(kind='material', household=True, revision=record['revision'],
                                 maps={s: f"materials/{row['id']}/{f}" for s, f in record['maps'].items()},
                                 params=record['params'])
    return result


def _params(change, current=None):
    if not isinstance(change, dict) or set(change) - set(DEFAULT_PARAMS):
        raise ValueError('Choose valid material parameters.')
    result = deepcopy(DEFAULT_PARAMS if current is None else current)
    result.update(change)
    if not isinstance(result['tint'], str) or not re.fullmatch(r'#[a-fA-F0-9]{6}', result['tint']):
        raise ValueError('Tint must be a six-digit hex colour.')
    for key, low, high in (('roughness', 0, 2), ('metalness', 0, 2), ('normal_scale', 0, 4),
                           ('ao_intensity', 0, 2), ('rotation_deg', 0, 359)):
        _number(result[key], low, high, key)
    tile = result['tile_ft']
    if not isinstance(tile, list) or len(tile) != 2:
        raise ValueError('tile_ft must contain width and height.')
    for axis in tile:
        _number(axis, .25, 200, 'tile_ft')
    if result['normal_convention'] not in ('gl', 'dx'):
        raise ValueError('normal_convention must be gl or dx.')
    if type(result['random_offset']) is not bool:
        raise ValueError('random_offset must be a boolean.')
    return result


def _number(value, low, high, name):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be from {low} to {high}.')


def _maps(mid, change, current=None):
    if not isinstance(change, dict) or set(change) - set(SLOTS):
        raise ValueError('Choose a valid texture slot.')
    result = dict(current or {})
    for slot, filename in change.items():
        if filename is None:
            result.pop(slot, None)
        elif (not isinstance(filename, str) or not re.fullmatch(r'maps/[a-f0-9]{12}\.(png|jpg)', filename)
              or not (root() / mid / filename).is_file()):
            raise ValueError('Choose an image already ingested for this material.')
        else:
            result[slot] = filename
    return result


def _fields(mid, fields, record):
    allowed = {'name', 'source', 'licence', 'source_url', 'based_on', 'params', 'maps', 'source_snapshot', 'archived'}
    if not isinstance(fields, dict) or set(fields) - allowed:
        raise ValueError('Choose valid material fields; material ids cannot change.')
    result = deepcopy(record)
    for key in allowed - {'params', 'maps', 'source_snapshot'}:
        if key in fields:
            result[key] = fields[key]
    if not isinstance(result['name'], str) or not result['name'].strip():
        raise ValueError('Give the material a name.')
    result['name'] = result['name'].strip()
    if result['source'] not in ('user', 'polyhaven', 'ambientcg', 'gltf'):
        raise ValueError('Choose a valid material source.')
    if type(result['archived']) is not bool:
        raise ValueError('archived must be a boolean.')
    for key in ('licence', 'source_url', 'based_on'):
        if result[key] is not None and not isinstance(result[key], str):
            raise ValueError(f'{key} must be text or null.')
    result['params'] = _params(fields.get('params', {}), record['params'])
    result['maps'] = _maps(mid, fields.get('maps', {}), record['maps'])
    if 'source_snapshot' in fields:
        if record['source_snapshot'] is not None:
            raise ValueError('The source snapshot is immutable. Duplicate the material for a new source.')
        snapshot = fields['source_snapshot']
        if snapshot is not None:
            if not isinstance(snapshot, dict) or set(snapshot) != {'maps', 'params'}:
                raise ValueError('A source snapshot contains maps and params.')
            snapshot = dict(maps=_maps(mid, snapshot['maps']), params=_params(snapshot['params']))
        result['source_snapshot'] = snapshot
    return result


def _history(mid):
    path = root() / mid / 'history.json'
    return _read(path) if path.exists() else {'undo': [], 'redo': []}


def _save(record, previous=None, history=None):
    mid = record['id']
    if history is None:
        history = _history(mid)
        if previous:
            history['undo'].append(previous['revision'])
        history['redo'] = []
    record['revision'] = previous['revision'] + 1 if previous else 1
    record['updated_at'] = datetime.now(timezone.utc).isoformat()
    _json(root() / mid / 'revisions' / f"{record['revision']}.json", record)
    _json(root() / mid / 'history.json', history)
    _json(root() / mid / 'material.json', record)
    _bump()
    return deepcopy(record)


def create(fields, actor) -> dict:
    mid = 'material-' + uuid.uuid4().hex
    with _lock(mid):
        record = dict(id=mid, name='', source='user', licence=None, source_url=None, based_on=None,
                      revision=0, archived=False, created_by=actor, updated_at=None, maps={},
                      params=deepcopy(DEFAULT_PARAMS), source_snapshot=None)
        record = _fields(mid, fields, record)
        return _save(record)


def _update(mid, change, actor):
    previous = _editable(mid)
    record = _fields(mid, change, previous)
    return _save(record, previous)


def update(material_id, change, actor) -> dict:
    with _lock(material_id):
        return _update(material_id, change, actor)


def _ingest(mid, slot, data):
    _editable(mid)
    return _image_file(mid, slot, data)


def _image_file(mid, slot, data):
    from PIL import Image
    if slot not in SLOTS:
        raise ValueError('Choose a valid texture slot.')
    if not isinstance(data, bytes) or not data or len(data) > MAX_INPUT_BYTES:
        raise ValueError('Each image must be at most 40 MB.')
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()  # Never publish a merely parseable header or truncated pixels.
            source.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
            decoded = source.convert('RGB' if slot == 'base_color' else 'RGBA' if 'A' in source.getbands() else 'RGB')
            out = io.BytesIO()
            decoded.save(out, format='JPEG' if slot == 'base_color' else 'PNG',
                         **({'quality': 92} if slot == 'base_color' else {}))
            encoded = out.getvalue()
    except Exception as exc:
        raise ValueError(f'Could not decode image: {exc}') from exc
    filename = 'maps/' + hashlib.sha256(encoded).hexdigest()[:12] + ('.jpg' if slot == 'base_color' else '.png')
    target = root() / mid / filename
    if not target.exists():
        files = list((root() / mid / 'maps').glob('*'))
        if len(files) >= MAX_FILES:
            raise ValueError('A material may have at most 12 image files, including retained revisions.')
        if sum(p.stat().st_size for p in files) + len(encoded) > MAX_MATERIAL_BYTES:
            raise ValueError('A material may have at most 200 MB of images.')
        _atomic(target, encoded)
    return filename


def ingest_image(material_id, slot, data: bytes) -> str:
    with _lock(material_id):
        return _ingest(material_id, slot, data)


def set_image(material_id, slot, data: bytes, actor) -> dict:
    """Ingest and attach under the same per-material lock (HTTP and chunk uploads)."""
    with _lock(material_id):
        filename = _ingest(material_id, slot, data)
        return _update(material_id, {'maps': {slot: filename}}, actor)


def duplicate(material_id, actor) -> dict:
    with _lock(material_id):
        source = get(material_id)
        mid = 'material-' + uuid.uuid4().hex
        # The new id is unpublished and inaccessible until material.json is written.
        with _lock(mid):
            record = deepcopy(source)
            record.update(id=mid, name=source['name'] + ' copy', source='user', based_on=material_id,
                          created_by=actor, archived=False, maps={}, source_snapshot=None)
            try:
                if source['source'] == 'builtin' and source['maps']:
                    try:
                        directory = Path(twin_library.ensure(material_id))
                    except OSError as exc:
                        raise ValueError('Source material files are unavailable.') from exc
                else:
                    directory = root() / material_id
                for slot, filename in source['maps'].items():
                    data = (directory / filename).read_bytes()
                    if source['source'] == 'builtin':
                        file = _image_file(mid, slot, data)
                    else:
                        file = filename
                        _atomic(root() / mid / file, data)
                    record['maps'][slot] = file
                record['source_snapshot'] = deepcopy({'maps': record['maps'], 'params': record['params']})
                return _save(record)
            except Exception:
                folder = root() / mid  # Generated id, always a direct child of materials.
                if folder.exists():
                    shutil.rmtree(folder)
                raise


def _labels(value, material_id, path='House'):
    labels = []
    if isinstance(value, dict):
        if value.get('id') == material_id:
            return [path]
        title = value.get('name') or value.get('id')
        if title:
            path += ' / ' + str(title)
        for key, child in value.items():
            labels.extend(_labels(child, material_id, path + ' / ' + key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            labels.extend(_labels(child, material_id, path + f' {index + 1}'))
    return labels


def uses(material_id) -> dict:
    _id(material_id)
    current = _labels(twin_store.current_model(), material_id)
    history = False
    for row in twin_store.rounds():
        document = _read(Path(twin_store.DATA_DIR) / 'rounds' / f"{row['id']}.json")
        if _labels(document, material_id):
            history = True
            break
    try:
        from services import twin_house_saves
    except ImportError:
        twin_house_saves = None
    if twin_house_saves and not history:
        for path in (Path(twin_store.DATA_DIR) / 'houses').glob('*.json'):
            if _labels(_read(path).get('model'), material_id):
                history = True
                break
    return {'current': current, 'history': history}


def delete(material_id, actor) -> dict:
    # Same order as chunk uploads and house mutations; prevent a house assignment
    # racing the last-reference check and purge.
    with twin_store.LIFECYCLE, twin_store._LOCK, _lock(material_id):
        _editable(material_id)
        references = uses(material_id)
        if references['current']:
            labels = references['current']
            raise ValueError(f"Used on {len(labels)} surfaces: " + ', '.join(labels))
        if references['history']:
            _update(material_id, {'archived': True}, actor)
            return {'archived': True}
        shutil.rmtree(root() / material_id)
        _bump()
        return {'archived': False}


def reset_to_source(material_id, actor) -> dict:
    with _lock(material_id):
        record = _editable(material_id)
        snapshot = record['source_snapshot']
        if snapshot is None:
            raise ValueError('This material has no source snapshot.')
        record['maps'] = deepcopy(snapshot['maps'])
        record['params'] = deepcopy(snapshot['params'])
        return _save(record, _editable(material_id))


def _step(mid, direction):
    with _lock(mid):
        previous = _editable(mid)
        history = _history(mid)
        if not history[direction]:
            raise ValueError(f'No material {direction} is available.')
        revision = history[direction].pop()
        history['redo' if direction == 'undo' else 'undo'].append(previous['revision'])
        record = _read(root() / mid / 'revisions' / f'{revision}.json')
        return _save(record, previous, history)


def undo(material_id) -> dict:
    return _step(material_id, 'undo')


def redo(material_id) -> dict:
    return _step(material_id, 'redo')


def file_path(material_id, filename) -> Path:
    _editable(material_id)
    if not isinstance(filename, str) or not re.fullmatch(r'maps/[a-f0-9]{12}\.(png|jpg)', filename):
        raise ValueError('No such material image.')
    path = root() / material_id / filename
    if not path.is_file():
        raise ValueError('No such material image.')
    return path
