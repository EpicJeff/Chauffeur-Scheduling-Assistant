"""Editable model records, shared by imported models and the built-in library.

All mutations share the house lifecycle lock with import uploads, object edits
and material deletion. Reads add defaults without rewriting legacy assets.
"""
from copy import deepcopy
import json
import logging
import os
from pathlib import Path

from services import twin_imports, twin_library, twin_model_parts, twin_store

EDITABLE = {'lod_percent', 'fix', 'materials', 'parts', 'parts_version'}
STATE_FIELDS = ('lod_percent', 'fix', 'materials')
LEVELS = ('lod0.glb', 'lod1.glb', 'lod2.glb')
MAX_HISTORY = 20
BUILTIN_FIELDS = EDITABLE | {'revision', '_lod_revisions'}
_LOGGER = logging.getLogger(__name__)


class Conflict(Exception):
    def __init__(self, current, message='This model changed in another tab. Reload its current record.'):
        super().__init__(message)
        self.current = deepcopy(current)


def canonical_asset_id(value):
    """Director and yard copies may carry Poly Haven's source prefix."""
    return value.removeprefix('polyhaven:') if isinstance(value, str) else value


def _path(asset_id):
    # Call only after get() has verified the id against imports/the manifest.
    asset_id = canonical_asset_id(asset_id)
    if asset_id.startswith('import-'):
        return twin_imports.root() / asset_id / twin_imports.META
    return Path(twin_store.DATA_DIR) / 'library_models' / f'{asset_id}.json'


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    os.replace(temp, path)


def get(asset_id):
    asset_id = canonical_asset_id(asset_id)
    imported = twin_imports.get(asset_id)
    if imported is not None:
        record = imported
        builtin = False
    else:
        entry = twin_library.manifest().get(asset_id) if isinstance(asset_id, str) else None
        if not entry or entry.get('kind') != 'model':
            raise KeyError(asset_id)
        builtin = True
        record = dict(entry, id=asset_id, name=entry.get('name') or asset_id.replace('_', ' ').capitalize(),
                      model=entry.get('model') or next((n for n in entry['files'] if n.endswith(('.gltf', '.glb'))), None))
        path = _path(asset_id)
        if path.exists():
            saved = json.loads(path.read_text(encoding='utf-8'))
            record.update({key: value for key, value in saved.items() if key in BUILTIN_FIELDS})
    return _response({**{k: deepcopy(v) for k, v in record.items() if not k.startswith('_')},
            'builtin': builtin, 'revision': record.get('revision', 0),
            'lod_percent': deepcopy(record.get('lod_percent', list(twin_model_parts.DEFAULT_LOD_PERCENT))),
            'lods': [{**deepcopy(lod), 'percent': lod.get('percent', twin_model_parts.DEFAULT_LOD_PERCENT[LEVELS.index(lod['name'])]),
                      'revision': lod.get('revision', 0)} for lod in record.get('lods', [])],
            'parts': deepcopy(record.get('parts', []))})


def catalog():
    with twin_store.LIFECYCLE, twin_store._LOCK:
        ids = [row['id'] for row in twin_imports.catalog()]
        ids += [key for key, row in twin_library.manifest().items() if row.get('kind') == 'model']
        return [get(asset_id) for asset_id in ids]


def _check_revision(record, revision):
    if type(revision) is not int or revision < 0:
        raise ValueError('Send the current whole-number model revision.')
    if revision != record['revision']:
        raise Conflict(record)


def _parts(value):
    if not isinstance(value, list):
        raise ValueError('Model parts must be a list.')
    seen = set()
    for part in value:
        if (not isinstance(part, dict) or set(part) != {'key', 'name', 'triangles', 'has_uv', 'opaque'}
                or not isinstance(part['key'], str) or not part['key'].strip()
                or part['key'] in seen or not (part['name'] is None or isinstance(part['name'], str))
                or type(part['triangles']) is not int or part['triangles'] < 0
                or type(part['has_uv']) is not bool or type(part['opaque']) is not bool):
            raise ValueError('Each part needs a unique key, name, triangle count, has_uv and opaque flags.')
        seen.add(part['key'])
    return deepcopy(value)


def validate_materials(value, parts, *, per_copy, previous=None, allow_archived=False):
    """Validate changed assignments; preserve unchanged stale references verbatim."""
    from services import twin_materials
    previous = previous or {}
    allow_archived = per_copy and allow_archived
    ids = {row['id'] for row in twin_materials.catalogue(include_archived=allow_archived)['materials']
           if allow_archived or not row.get('archived')}
    changed = ({key: entry for key, entry in value.items() if key not in previous or entry != previous[key]}
               if isinstance(value, dict) else value)
    try:
        clean = twin_model_parts.validate_model_materials(changed, parts, ids, per_copy=per_copy)
    except (TypeError, KeyError) as exc:
        raise ValueError('Choose valid part materials from the Library.') from exc
    return {key: deepcopy(clean[key] if key in clean else previous[key]) for key in value}


def _history_path(asset_id):
    asset_id = canonical_asset_id(asset_id)
    path = _path(asset_id)
    return path.with_name('.model-history.json' if asset_id.startswith('import-') else f'.{asset_id}.history.json')


def history(asset_id):
    get(asset_id)
    path = _history_path(asset_id)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'undo': [], 'redo': []}


def _state(record):
    return {key: deepcopy(record[key]) for key in STATE_FIELDS if key in record}


def _save(record, previous, steps):
    path = _path(record['id'])
    raw = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    # Retain counters even after a percentage invalidates the visible lod entry.
    counters = raw.get('_lod_revisions', {})
    for lod in previous['lods']:
        counters[lod['name']] = max(counters.get(lod['name'], 0), lod.get('revision', 0))
    record = deepcopy(record)
    obsolete = []
    for i, name in enumerate(LEVELS):
        if previous['lod_percent'][i] != record['lod_percent'][i] or i == 0 and record['lod_percent'][0] == 100:
            generated = any(l['name'] == name for l in previous['lods']) or name in counters
            record['lods'] = [l for l in record['lods'] if l['name'] != name]
            if not record['builtin'] and generated and name != record['model']:
                record['files'].pop(name, None)
                obsolete.append(path.parent / name)
    record['revision'] = previous['revision'] + 1
    stored = {k: v for k, v in record.items()
              if k in BUILTIN_FIELDS} if record['builtin'] else {
                  k: v for k, v in record.items() if k not in ('builtin', 'orphans')}
    if counters:
        stored['_lod_revisions'] = counters
    _json(path, stored)
    # After publication these files are no longer addressable. A failed record
    # write leaves the old record and all its generated bytes intact.
    for filename in obsolete:
        try:
            filename.unlink(missing_ok=True)
        except OSError:
            _LOGGER.warning('Unable to remove obsolete model level %s', filename, exc_info=True)
    try:
        _json(_history_path(record['id']), {k: v[-MAX_HISTORY:] for k, v in steps.items()})
    except OSError:
        _LOGGER.warning('Unable to save model history for %s', record['id'], exc_info=True)
    return _response(get(record['id']))


def _response(record):
    keys = {p['key'] for p in record['parts']}
    orphans = [key for key in record.get('materials', {}) if key not in keys]
    if orphans:
        record['orphans'] = orphans
    return record


def update(asset_id, changes, revision):
    with twin_store.LIFECYCLE, twin_store._LOCK:
        previous = get(asset_id)
        _check_revision(previous, revision)
        if not isinstance(changes, dict) or not changes or set(changes) - EDITABLE:
            raise ValueError('Choose model detail levels, a fix, part materials or a first parts stamp.')
        record = deepcopy(previous)
        if 'parts' in changes or 'parts_version' in changes:
            if previous.get('parts_version'):
                raise ValueError('This model already has its parts stamp.')
            if 'parts' in changes:
                record['parts'] = _parts(changes['parts'])
            if 'parts_version' in changes:
                if type(changes['parts_version']) is not int or changes['parts_version'] != 1:
                    raise ValueError('The supported parts version is 1.')
                if not record['parts']:
                    raise ValueError('Stamp the model with at least one part before setting its parts version.')
                record['parts_version'] = 1
        if 'lod_percent' in changes:
            if previous['builtin']:
                raise ValueError('Built-in models keep their own detail levels.')
            record['lod_percent'] = twin_model_parts.validate_lod_percent(changes['lod_percent'])
        if 'fix' in changes:
            record['fix'] = twin_model_parts.validate_fix(changes['fix'])
        if 'materials' in changes:
            record['materials'] = validate_materials(changes['materials'], record['parts'], per_copy=False,
                                                    previous=previous.get('materials'))
        steps = history(asset_id)
        steps['undo'].append(_state(previous))
        steps['redo'] = []
        return _save(record, previous, steps)


def _step(asset_id, revision, direction):
    with twin_store.LIFECYCLE, twin_store._LOCK:
        previous = get(asset_id)
        _check_revision(previous, revision)
        steps = history(asset_id)
        if not steps[direction]:
            raise ValueError(f'No model {direction} is available.')
        state = steps[direction].pop()
        steps['redo' if direction == 'undo' else 'undo'].append(_state(previous))
        record = {k: deepcopy(v) for k, v in previous.items() if k not in STATE_FIELDS}
        record.update(state)
        return _save(record, previous, steps)


def undo(asset_id, revision):
    return _step(asset_id, revision, 'undo')


def redo(asset_id, revision):
    return _step(asset_id, revision, 'redo')


def reset(asset_id, revision):
    with twin_store.LIFECYCLE, twin_store._LOCK:
        previous = get(asset_id)
        _check_revision(previous, revision)
        record = {k: deepcopy(v) for k, v in previous.items() if k not in STATE_FIELDS}
        record['lod_percent'] = list(twin_model_parts.DEFAULT_LOD_PERCENT)
        steps = history(asset_id)
        steps['undo'].append(_state(previous))
        steps['redo'] = []
        return _save(record, previous, steps)
