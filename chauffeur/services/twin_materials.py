"""Household PBR assets. Material history is independent of house history.

Records publish atomically; maps are immutable and addressed by their encoded bytes.
Old maps remain available for source reset, material undo, and house/save references.
"""
from copy import deepcopy
from collections import Counter
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
DEFAULT_PARAMS = dict(tint='#ffffff', roughness=None, metalness=None, normal_scale=1,
                      normal_convention='gl', ao_intensity=1, tile_ft=[4, 4],
                      rotation_deg=0, random_offset=False)
MAX_INPUT_BYTES = 40 * 1024 * 1024
MAX_FILES = 16
MAX_MATERIAL_BYTES = 200 * 1024 * 1024
MAX_SIDE = 4096
MAX_INPUT_SIDE = 16384
MAX_INPUT_PIXELS = 64_000_000
MAX_REVISIONS = 20
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


def builtin_rows(kit_id='modern_farmhouse'):
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
    row = next((r for r in builtin_rows() if r['id'] == mid), None)
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


def require_editable(material_id):
    record = get(material_id)
    if record['source'] == 'builtin':
        raise ValueError('Built-in materials are read-only. Duplicate this material first.')
    return record


def catalogue(include_archived=False) -> dict:
    rows = builtin_rows()
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
        if key in ('roughness', 'metalness') and result[key] is None:
            continue  # Auto: a map multiplier or the source's flat default.
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
    allowed = {'name', 'licence', 'source_url', 'based_on', 'params', 'maps'}
    if not isinstance(fields, dict) or set(fields) - allowed:
        raise ValueError('Choose valid material fields; material ids cannot change.')
    result = deepcopy(record)
    for key in allowed - {'params', 'maps'}:
        if key in fields:
            result[key] = fields[key]
    if not isinstance(result['name'], str) or not result['name'].strip():
        raise ValueError('Give the material a name.')
    result['name'] = result['name'].strip()
    for key in ('licence', 'source_url', 'based_on'):
        if result[key] is not None and not isinstance(result[key], str):
            raise ValueError(f'{key} must be text or null.')
    result['params'] = _params(fields.get('params', {}), record['params'])
    result['maps'] = _maps(mid, fields.get('maps', {}), record['maps'])
    _check_live_limits(mid, result)
    return result


def _set_source(record, source, snapshot):
    """Internal source initialization for copies and future download/import jobs."""
    if source not in ('user', 'polyhaven', 'ambientcg', 'gltf'):
        raise ValueError('Choose a valid material source.')
    if record['source_snapshot'] is not None:
        raise ValueError('The source snapshot is immutable.')
    if not isinstance(snapshot, dict) or set(snapshot) != {'maps', 'params'}:
        raise ValueError('A source snapshot contains maps and params.')
    record['source'] = source
    record['source_snapshot'] = dict(maps=_maps(record['id'], snapshot['maps']), params=_params(snapshot['params']))
    _check_live_limits(record['id'], record)


def _map_refs(record):
    return set(record.get('maps', {}).values()) | set((record.get('source_snapshot') or {}).get('maps', {}).values())


def _check_live_limits(mid, record, pending=None):
    files = _map_refs(record)
    if len(files) > MAX_FILES:
        raise ValueError('A material may have at most 16 live image files.')
    pending = pending or {}
    size = sum(pending[filename] if filename in pending else (root() / mid / filename).stat().st_size
               for filename in files)
    if size > MAX_MATERIAL_BYTES:
        raise ValueError('A material may have at most 200 MB of live images.')


def _revision_paths(mid):
    return sorted((p for p in (root() / mid / 'revisions').glob('*.json') if p.stem.isdigit()),
                  key=lambda p: int(p.stem))


def _gc(mid, record, kept):
    referenced = _map_refs(record)
    for path in kept:
        referenced.update(_map_refs(_read(path)))
    for path in _revision_paths(mid):
        if path not in kept:
            path.unlink()
    for path in (root() / mid / 'maps').glob('*'):
        if 'maps/' + path.name not in referenced:
            path.unlink()


def _history(mid):
    path = root() / mid / 'history.json'
    return _read(path) if path.exists() else {'undo': [], 'redo': []}


def _save(record, previous=None, history=None, *, snapshot=True):
    mid = record['id']
    if history is None:
        history = _history(mid)
        if previous:
            history['undo'].append(history.get('head', previous['revision']))
        history['redo'] = []
    record['revision'] = previous['revision'] + 1 if previous else 1
    record['updated_at'] = datetime.now(timezone.utc).isoformat()
    if snapshot:
        _json(root() / mid / 'revisions' / f"{record['revision']}.json", record)
        history['head'] = record['revision']
    kept = _revision_paths(mid)[-MAX_REVISIONS:]
    revision_ids = {int(path.stem) for path in kept}
    history = {**history, **{key: [revision for revision in history[key] if revision in revision_ids]
                            for key in ('undo', 'redo')}}
    _json(root() / mid / 'history.json', history)
    _json(root() / mid / 'material.json', record)
    _bump()
    _gc(mid, record, kept)
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
    previous = require_editable(mid)
    record = _fields(mid, change, previous)
    return _save(record, previous)


def update(material_id, change, actor) -> dict:
    with _lock(material_id):
        return _update(material_id, change, actor)


def _ingest(mid, slot, data):
    record = require_editable(mid)
    return _image_file(mid, slot, data, record)


def _image_file(mid, slot, data, record):
    from PIL import Image
    if slot not in SLOTS:
        raise ValueError('Choose a valid texture slot.')
    if not isinstance(data, bytes) or not data or len(data) > MAX_INPUT_BYTES:
        raise ValueError('Each image must be at most 40 MB.')
    try:
        with Image.open(io.BytesIO(data)) as source:
            if (max(source.size) > MAX_INPUT_SIDE or source.width * source.height > MAX_INPUT_PIXELS):
                raise ValueError('Image dimensions must be at most 16384 per side and 64 Mpx.')
            if source.format == 'JPEG':
                source.draft('RGB', (MAX_SIDE, MAX_SIDE))
            source.load()  # Never publish a merely parseable header or truncated pixels.
            if source.mode == 'I' or source.mode.startswith('I;16'):
                source = source.convert('I').point(lambda value: value / 257).convert('L')
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
    projected = deepcopy(record)
    projected['maps'][slot] = filename
    _check_live_limits(mid, projected, {filename: len(encoded)})
    if not target.exists():
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
            if source['source'] == 'builtin':
                matches = [(role, ref) for role, ref in twin_library.kit('modern_farmhouse')['materials'].items()
                           if ref['asset'] == material_id]
                # granite_tile also serves counters; retain granite's explicit
                # finish rather than taking the first generic counter ref.
                role, ref = next(((role, ref) for role, ref in matches if 'roughness' in ref),
                                 matches[0] if matches else ('material', {}))
                record['params'].update(roughness=ref.get('roughness', .45 if role == 'roof' else .85),
                                        metalness=.45 if role == 'roof' else 0)
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
                        file = _image_file(mid, slot, data, record)
                    else:
                        file = filename
                        _atomic(root() / mid / file, data)
                    record['maps'][slot] = file
                _set_source(record, 'user', {'maps': record['maps'], 'params': record['params']})
                return _save(record)
            except Exception:
                folder = root() / mid  # Generated id, always a direct child of materials.
                if folder.exists():
                    shutil.rmtree(folder)
                raise


def _labels(value, material_id, owner='House', kind='surfaces', feature=False):
    """One human label per reference; delete groups equal labels with counts."""
    labels = []
    if isinstance(value, dict):
        if value.get('id') == material_id:
            return [f'{owner} {kind}']
        for key, child in value.items():
            if key == 'buildings' and isinstance(child, list):
                for building in child:
                    labels.extend(_labels(building, material_id, building.get('name') or 'House'))
            elif key == 'site' and isinstance(child, dict):
                from services.twin_site_shapes import pieces
                names = {'fence': 'Fence', 'pool': 'Pool', 'beds': 'Planting bed', 'hardscape': 'Patio',
                         'edges': 'Lawn edge', 'fire_pit': 'Fire pit', 'terraces': 'Retaining wall'}
                for collection, content in child.items():
                    if collection in names:
                        for piece in pieces(content):
                            name = piece.get('name') or ('Path' if piece.get('kind') == 'path' else names[collection])
                            labels.extend(_labels(piece, material_id, name, 'surface', True))
                    else:
                        labels.extend(_labels(content, material_id, owner, kind))
            elif key == 'materials' and isinstance(child, dict):
                for part, slot in child.items():
                    labels.extend(_labels(slot, material_id, owner,
                                          part.replace('_', ' ') if feature else _surface_kind(part, kind), feature))
            else:
                labels.extend(_labels(child, material_id, owner, _surface_kind(key, kind), feature))
    elif isinstance(value, list):
        for child in value:
            labels.extend(_labels(child, material_id, owner, kind, feature))
    return labels


def _surface_kind(key, default):
    return {'walls': 'walls', 'wall_material': 'walls', 'interior_wall': 'walls', 'siding': 'walls',
            'floor': 'floors', 'floor_material': 'floors', 'ceiling': 'ceilings', 'ceiling_material': 'ceilings',
            'porch_ceiling': 'ceilings', 'roof': 'roof', 'roofs': 'roof', 'roof_material': 'roof',
            'base': 'foundation', 'foundation': 'foundation'}.get(key, default)


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
        previous = require_editable(material_id)
        references = uses(material_id)
        if references['current']:
            labels = references['current']
            grouped = [f'{label} ({count})' for label, count in Counter(labels).items()]
            raise ValueError(f"Used on {len(labels)} surfaces: " + ', '.join(grouped))
        if references['history']:
            record = deepcopy(previous)
            record['archived'] = True
            _save(record, previous)
            return {'archived': True}
        shutil.rmtree(root() / material_id)
        _bump()
        return {'archived': False}


def reset_to_source(material_id, actor) -> dict:
    with _lock(material_id):
        record = require_editable(material_id)
        snapshot = record['source_snapshot']
        if snapshot is None:
            raise ValueError('This material has no source snapshot.')
        record['maps'] = deepcopy(snapshot['maps'])
        record['params'] = deepcopy(snapshot['params'])
        return _save(record, require_editable(material_id))


def _step(mid, direction):
    with _lock(mid):
        previous = require_editable(mid)
        history = _history(mid)
        if not history[direction]:
            raise ValueError(f'No material {direction} is available.')
        revision = history[direction].pop()
        history['redo' if direction == 'undo' else 'undo'].append(history.get('head', previous['revision']))
        history['head'] = revision
        record = _read(root() / mid / 'revisions' / f'{revision}.json')
        for key in ('archived', 'source', 'source_snapshot'):
            record[key] = deepcopy(previous[key])
        # Moving the cursor still increases the public cache revision, but does
        # not evict another undo target by writing a duplicate content snapshot.
        return _save(record, previous, history, snapshot=False)


def undo(material_id) -> dict:
    return _step(material_id, 'undo')


def redo(material_id) -> dict:
    return _step(material_id, 'redo')


def file_path(material_id, filename) -> Path:
    try:
        record = get(material_id)
    except ValueError as exc:
        raise FileNotFoundError('No such material image.') from exc
    if record['source'] == 'builtin':
        raise FileNotFoundError('No such material image.')
    if not isinstance(filename, str) or not re.fullmatch(r'maps/[a-f0-9]{12}\.(png|jpg)', filename):
        raise FileNotFoundError('No such material image.')
    path = root() / material_id / filename
    if not path.is_file():
        raise FileNotFoundError('No such material image.')
    return path
