"""File-backed twin rounds and sources, with metadata in household settings."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import uuid

from services import storage, twin_pdf, twin_plan

DATA_DIR = os.path.join(os.path.dirname(storage.DB_PATH), 'twin')
_LOCK = threading.Lock()
_KINDS = {'draft', 'director', 'hand', 'revert'}
_PHOTO_MIMES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}


class StaleRound(Exception):
    """A person's edit was based on a round that is no longer current."""


def _state():
    row = deepcopy(storage.get_settings().get('house_twin') or {})
    row.setdefault('current', None)
    for key in ('rounds', 'fixes', 'sources'):
        row.setdefault(key, [])
    return row


def _save(row):
    storage.patch_settings({'house_twin': row})


def _read_round(row, round_id):
    if type(round_id) is not int or not any(r['id'] == round_id for r in row['rounds']):
        raise KeyError(round_id)
    with open(os.path.join(DATA_DIR, 'rounds', f'{round_id}.json'), encoding='utf-8') as file:
        return json.load(file)


def current() -> dict | None:
    with _LOCK:
        row = _state()
        return _read_round(row, row['current']) if row['current'] is not None else None


def current_id() -> int | None:
    with _LOCK:
        return _state()['current']


def rounds() -> list[dict]:
    with _LOCK:
        return _state()['rounds']


def _check_base(base):
    if base is not None and (type(base) is not int or base < 1):
        raise ValueError('The base must be a round id.')


def _append_round(row, plan, kind, note='', cost=None, run=None, base=None, changes=()):
    """Called with _LOCK held; file, pointer and fixes form one mutation."""
    round_id = max((r['id'] for r in row['rounds']), default=0) + 1
    at = datetime.now(timezone.utc).isoformat()
    stale = base is not None and base != row['current']
    record = {'id': round_id, 'kind': kind, 'created': at, 'note': note,
              'cost': cost, 'run': run, 'stale': stale}
    root = Path(DATA_DIR) / 'rounds'
    root.mkdir(parents=True, exist_ok=True)
    target = root / f'{round_id}.json'
    # A same-directory temp file keeps the rename on the same filesystem.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=root,
                                         suffix='.tmp', delete=False) as file:
            temp_path = Path(file.name)
            json.dump(plan, file, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, target)
        row['rounds'].append(record)
        if not stale:
            row['current'] = round_id
        row['fixes'].extend({**change, 'round': round_id, 'at': at} for change in changes)
        _save(row)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return round_id


def push_round(plan: dict, kind: str, note: str = '', cost: float | None = None,
               run: str | None = None, base: int | None = None) -> int:
    with _LOCK:
        if kind not in _KINDS:
            raise ValueError('Unknown twin round kind.')
        _check_base(base)
        plan, _ = twin_plan.normalize(plan)
        return _append_round(_state(), plan, kind, note, cost, run, base)


def revert(round_id: int) -> int:
    """Copy a historical plan into a new current round and return its int id."""
    with _LOCK:
        row = _state()
        return _append_round(row, _read_round(row, round_id), 'revert')


def _leaf(plan, path):
    value = plan
    for key, index in re.findall(r'([^.[\]]+)|\[(\d+)\]', path):
        try:
            value = value[int(index)] if index else value[key]
        except (KeyError, IndexError, TypeError):
            return None
    return deepcopy(value)


def save_hand_edit(plan: dict, reason: str, base: int | None = None) -> int:
    with _LOCK:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('A hand edit needs a reason.')
        _check_base(base)
        row = _state()
        if base is not None and base != row['current']:
            raise StaleRound('The twin has changed. Reload it before saving this edit.')
        plan, _ = twin_plan.normalize(plan)
        before = _read_round(row, row['current']) if row['current'] is not None else None
        # The first save establishes the plan; it corrects no previous leaves.
        changes = [] if before is None else [
            {'path': path, 'before': _leaf(before, path), 'after': _leaf(plan, path),
             'reason': reason}
            for path in twin_plan.diff_paths(before, plan)
        ]
        return _append_round(row, plan, 'hand', note=reason, base=base, changes=changes)


def fixes() -> list[dict]:
    with _LOCK:
        return _state()['fixes']


def save_source(kind: str, filename: str, data: bytes, *, content_type: str | None = None) -> str:
    """Keep original bytes; PDF page images are rendered only during upload."""
    with _LOCK:
        if kind not in ('drawing', 'photo'):
            raise ValueError('A source must be a drawing or photo.')
        if not data:
            raise ValueError('The source is empty.')
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError('The source needs a filename.')
        if kind == 'drawing':
            images = twin_pdf.render_pages(data)
            mime, suffix = 'application/pdf', '.pdf'
        else:
            mime = _PHOTO_MIMES.get(Path(filename).suffix.lower()) or content_type
            if mime not in _PHOTO_MIMES.values():
                raise ValueError('Photos must be JPEG or PNG images.')
            suffix = '.png' if mime == 'image/png' else '.jpg'
            images = []
        source_id = uuid.uuid4().hex
        root = Path(DATA_DIR) / 'sources' / source_id
        root.mkdir(parents=True)
        try:
            (root / ('original' + suffix)).write_bytes(data)
            for image in images:
                (root / f"{image['page']}.png").write_bytes(base64.b64decode(image['b64']))
            record = {'id': source_id, 'kind': kind, 'filename': filename,
                      'pages': len(images) if kind == 'drawing' else 1, 'mime': mime}
            row = _state()
            row['sources'].append(record)
            _save(row)
        except Exception:
            shutil.rmtree(root)
            raise
        return source_id


def sources() -> list[dict]:
    with _LOCK:
        return _state()['sources']


def source_images(source_id: str, pages: list[int] | None = None) -> list[dict]:
    with _LOCK:
        source = next((s for s in _state()['sources'] if s['id'] == source_id), None)
        if source is None:
            raise KeyError(source_id)
        selected = list(range(1, source['pages'] + 1)) if pages is None else pages
        if not isinstance(selected, list) or any(type(p) is not int or not 1 <= p <= source['pages']
                                                 for p in selected):
            raise ValueError('Source page numbers are 1-based and must exist.')
        root = Path(DATA_DIR) / 'sources' / source['id']
        images = []
        for page in selected:
            if source['kind'] == 'drawing':
                path, mime = root / f'{page}.png', 'image/png'
            else:
                mime = source['mime']
                path = root / ('original.png' if mime == 'image/png' else 'original.jpg')
            images.append({'mime': mime, 'b64': base64.b64encode(path.read_bytes()).decode('ascii')})
        return images
