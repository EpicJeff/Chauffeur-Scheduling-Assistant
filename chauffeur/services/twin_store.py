"""File-backed twin rounds and sources, with metadata in household settings."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import tempfile
import threading
import uuid
import weakref

from PIL import Image, ImageOps

from services import storage, twin_pdf, twin_plan

DATA_DIR = os.path.join(os.path.dirname(storage.DB_PATH), 'twin')
_LOCK = threading.RLock()
LIFECYCLE = threading.RLock()
_MASTER_LOCKS = weakref.WeakValueDictionary()  # Only active page readers retain locks.
build_running = lambda: False  # Task 8 supplies the build runner's predicate.
stop_builds_for_start_over = lambda: None
_KINDS = {'draft', 'director', 'hand', 'revert', 'build', 'edit', 'start_over'}
_PAGE_ROLES = {'floor', 'roof', 'plot', 'elevation', 'other', 'skip'}
# Pillow identifies multi-picture phone JPEGs as MPO.
_PHOTO_MIMES = {'JPEG': 'image/jpeg', 'MPO': 'image/jpeg', 'PNG': 'image/png'}


class StaleRound(Exception):
    """A person's edit was based on a round that is no longer current."""


class StaleGeneration(ValueError):
    """A worker belongs to a house that has since been started over."""


def _state():
    row = deepcopy(storage.get_settings().get('house_twin') or {})
    row.setdefault('current', None)
    row.setdefault('generation', 0)
    for key in ('rounds', 'fixes', 'sources', 'page_roles', 'registrations', 'tombstones'):
        row.setdefault(key, [])
    return row


def _save(row):
    storage.patch_settings({'house_twin': row})


def generation() -> int:
    with _LOCK:
        return _state()['generation']


def start_over() -> None:
    """Clear the house and its files, retaining spend and panel measurements."""
    with LIFECYCLE, _LOCK:
        stop_builds_for_start_over()
        if build_running():
            raise ValueError('Stop the build before starting over.')
        next_generation = _state()['generation'] + 1
        root = Path(DATA_DIR).resolve()
        targets = [root / name for name in ('rounds', 'sources', 'runs', 'builds')]
        # Validate every target before deleting any files, including on Windows.
        if any(not target.resolve().is_relative_to(root) for target in targets):
            raise ValueError('Twin files must stay within the twin data directory.')
        # Invalidate late workers and clear pointers before any fallible deletion.
        _save({'generation': next_generation})
        for target in targets:
            if target.is_symlink():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target)


def add_tombstone(piece: dict) -> None:
    if (not isinstance(piece, dict) or not isinstance(piece.get('kind'), str)
            or 'level' not in piece
            or (piece['level'] is not None and not isinstance(piece['level'], str))
            or not isinstance(piece.get('geometry'), dict)
            or not isinstance(piece.get('src'), dict)):
        raise ValueError('A deleted piece needs kind, level, geometry and src.')
    with _LOCK:
        row = _state()
        row['tombstones'].append(deepcopy(piece))
        _save(row)


def tombstones() -> list[dict]:
    with _LOCK:
        return _state()['tombstones']


def perf_results() -> list[dict]:
    """Panel measurements, oldest first, independent of plan revisions."""
    with _LOCK:
        return deepcopy(storage.get_settings().get('house_twin_perf') or [])


def save_perf(body: dict) -> dict:
    record = {}
    for key in ('tier', 'gpu', 'ua', 'at'):
        value = body.get(key)
        if not isinstance(value, str) or len(value) > 300:
            raise ValueError(f'{key} must be a string of at most 300 characters.')
        record[key] = value
    if record['tier'] not in ('low', 'high'):
        raise ValueError('tier must be low or high.')
    for key in ('fpsAvg', 'fpsP5', 'drawCalls', 'triangles'):
        value = body.get(key)
        if type(value) not in (int, float) or value < 0 or (type(value) is float and not math.isfinite(value)):
            raise ValueError(f'{key} must be a finite non-negative number.')
        record[key] = value
    with _LOCK:
        rows = storage.get_settings().get('house_twin_perf') or []
        storage.patch_settings({'house_twin_perf': [*rows, record][-20:]})
    return record


def _read_round(row, round_id):
    if type(round_id) is not int or not any(r['id'] == round_id for r in row['rounds']):
        raise KeyError(round_id)
    with open(os.path.join(DATA_DIR, 'rounds', f'{round_id}.json'), encoding='utf-8') as file:
        return twin_plan.normalize(json.load(file))[0]


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


def _append_round(row, plan, kind, note='', cost=None, run=None, base=None, changes=(), step=None):
    """Called with _LOCK held; file, pointer and fixes form one mutation."""
    round_id = max((r['id'] for r in row['rounds']), default=0) + 1
    at = datetime.now(timezone.utc).isoformat()
    stale = base is not None and base != row['current']
    record = {'id': round_id, 'kind': kind, 'created': at, 'note': note,
              'cost': cost, 'run': run, 'stale': stale}
    if step is not None:
        record['step'] = deepcopy(step)
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
               run: str | None = None, base: int | None = None, step: dict | None = None,
               generation: int | None = None) -> int:
    with _LOCK:
        row = _state()
        if generation is not None and generation != row['generation']:
            raise StaleGeneration('The house was started over. Discard this result.')
        if kind not in _KINDS:
            raise ValueError('Unknown twin round kind.')
        _check_base(base)
        plan, _ = twin_plan.normalize(plan)
        return _append_round(row, plan, kind, note, cost, run, base, step=step)


def update_current(mutator, kind, note='', step=None, cost=None, generation=None) -> int:
    """Apply a mutation to the latest plan and publish it without a stale base."""
    with LIFECYCLE, _LOCK:
        row = _state()
        if generation is not None and generation != row['generation']:
            raise StaleGeneration('The house was started over. Discard this result.')
        if kind not in _KINDS:
            raise ValueError('Unknown twin round kind.')
        before = _read_round(row, row['current']) if row['current'] is not None else None
        plan, _ = twin_plan.normalize(mutator(before))
        return _append_round(row, plan, kind, note=note, cost=cost, step=step)


def revert(round_id: int, generation=None) -> int:
    """Copy a historical plan into a new current round and return its int id."""
    with _LOCK:
        expected = _state()['generation'] if generation is None else generation
    with LIFECYCLE, _LOCK:
        row = _state()
        if expected != row['generation']:
            raise StaleGeneration('The house was started over. Discard this result.')
        if build_running():
            raise ValueError('Stop the build before returning to an earlier house.')
        return _append_round(row, _read_round(row, round_id), 'revert')


def _leaf(plan, path):
    value = plan
    for key, selector in re.findall(r'([^.[\]]+)|\[([^\]]+)\]', path):
        try:
            if not selector:
                value = value[key]
            elif selector.startswith(('id=', 'name=')):
                field, selected = selector.split('=', 1)
                value = next(item for item in value if isinstance(item, dict)
                             and field in item and str(item[field]) == selected)
            else:
                value = value[int(selector)]
        except (KeyError, IndexError, TypeError, ValueError, StopIteration):
            return None
    return deepcopy(value)


def _fix_kind(path):
    if path.startswith('site.compose_overrides'):
        return None
    if path.startswith('site.'):
        feature = path[5:].split('.', 1)[0].split('[', 1)[0]
        return 'extraction' if feature in ('lot', 'hardscape', 'pool', 'fire_pit') else 'yard'
    return 'extraction'


def save_hand_edit(plan: dict, reason: str, base: int | None = None) -> int:
    with _LOCK:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('A hand edit needs a reason.')
        _check_base(base)
        row = _state()
        if base is not None and base != row['current']:
            raise StaleRound('The twin has changed. Reload it before saving this edit.')
        before = _read_round(row, row['current']) if row['current'] is not None else None
        if before is not None:
            plan = twin_plan.record_compose_overrides(before, plan)
        # The first save establishes the plan; it corrects no previous leaves.
        # Log the person's edits before normalization drops dependent geometry
        # (e.g. an opening on a removed wall) and shifts positional list items.
        changes = [] if before is None else [
            {'path': path, 'kind': _fix_kind(path), 'before': _leaf(before, path), 'after': _leaf(plan, path),
             'reason': reason}
            for path in twin_plan.diff_paths(before, plan)
            if _fix_kind(path) is not None
        ]
        plan, _ = twin_plan.normalize(plan)
        return _append_round(row, plan, 'hand', note=reason, base=base, changes=changes)


def fixes() -> list[dict]:
    with _LOCK:
        return _state()['fixes']


def save_source(kind: str, filename: str, data: bytes, *, content_type: str | None = None) -> str:
    """Verify photos and render drawings before locking their storage writes."""
    if kind not in ('drawing', 'photo'):
        raise ValueError('A source must be a drawing or photo.')
    if not data:
        raise ValueError('The source is empty.')
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError('The source needs a filename.')
    source_generation = generation()
    if kind == 'drawing':
        pages = [(f"{page['page']}.png", base64.b64decode(page['b64']))
                 for page in twin_pdf.render_pages(data)]
        mime, suffix = 'application/pdf', '.pdf'
        total_pages = twin_pdf.page_count(data)
    else:
        try:
            with Image.open(io.BytesIO(data)) as image:
                mime = _PHOTO_MIMES.get(image.format)
                if mime is None:
                    raise ValueError('Photos must be JPEG or PNG images.')
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                upright = ImageOps.exif_transpose(image)
                upright.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                with io.BytesIO() as output:
                    upright.convert('RGB').save(output, format='JPEG', quality=88)
                    derivative = output.getvalue()
        except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
            raise ValueError('Photos must be readable JPEG or PNG images.') from exc
        suffix = '.png' if mime == 'image/png' else '.jpg'
        pages = []
    source_id = uuid.uuid4().hex
    record = {'id': source_id, 'kind': kind, 'filename': filename,
              'pages': len(pages) if kind == 'drawing' else 1, 'mime': mime}
    if kind == 'drawing':
        record['total_pages'] = total_pages
    root = Path(DATA_DIR) / 'sources' / source_id
    try:
        with LIFECYCLE, _LOCK:
            if source_generation != _state()['generation']:
                raise StaleGeneration('The house was started over during the upload.')
            root.mkdir(parents=True)
            (root / ('original' + suffix)).write_bytes(data)
            if kind == 'photo':
                (root / 'model.jpg').write_bytes(derivative)
            for name, png in pages:
                (root / name).write_bytes(png)
        if kind == 'drawing':
            for page in range(1, record['pages'] + 1):
                with twin_pdf.render_page(data, page, dpi=300, max_side=7200,
                                          grayscale=True) as master:
                    _write_master(root / f'master-{page}.png', master, source_generation)
        with _LOCK:
            if source_generation != _state()['generation']:
                raise StaleGeneration('The house was started over during the upload.')
            row = _state()
            row['sources'].append(record)
            _save(row)
    except Exception:
        with LIFECYCLE:
            if root.exists():
                shutil.rmtree(root)
        raise
    return source_id


def _write_master(target, image, source_generation):
    """Stream a PNG to an adjacent temporary file, then publish it atomically."""
    with LIFECYCLE:
        with _LOCK:
            if source_generation != _state()['generation']:
                raise StaleGeneration('The house was started over while rendering the sheet.')
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, suffix='.tmp', delete=False) as file:
                temp_path = Path(file.name)
                image.save(file, format='PNG')
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def sources() -> list[dict]:
    with _LOCK:
        return _state()['sources']


def _source_page(row, source_id, page):
    source = next((s for s in row['sources'] if s['id'] == source_id), None)
    if source is None:
        raise ValueError('The source does not exist.')
    if type(page) is not int or not 1 <= page <= source['pages']:
        raise ValueError('Source page numbers are 1-based and must exist.')
    return source


def _box(box):
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in box)
            or box[0] >= box[2] or box[1] >= box[3]):
        raise ValueError('A box must be [x0, y0, x1, y1] within 0..1 with positive area.')
    return list(box)


def set_page_roles(rows) -> None:
    """Replace all page roles only after every supplied row has validated."""
    if not isinstance(rows, list):
        raise ValueError('Page roles must be a list.')
    with _LOCK:
        row = _state()
        checked = []
        for item in rows:
            if not isinstance(item, dict):
                raise ValueError('A page role must be an object.')
            _source_page(row, item.get('source'), item.get('page'))
            if not isinstance(item.get('role'), str) or item['role'] not in _PAGE_ROLES:
                raise ValueError('Unknown page role.')
            building = item.get('building', 'house')
            if not isinstance(building, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', building):
                raise ValueError('A building needs a valid id of at most 64 characters.')
            level = item.get('level')
            if level is not None and (not isinstance(level, str) or not level.strip() or len(level) > 80):
                raise ValueError('A level must be null or a non-empty string of at most 80 characters.')
            box = None if item.get('box') is None else _box(item['box'])
            checked.append({'source': item['source'], 'page': item['page'],
                            'role': item['role'], 'level': level,
                            'box': box, 'building': building})
        row['page_roles'] = checked
        _save(row)


def page_roles() -> list[dict]:
    with _LOCK:
        return _state()['page_roles']


def registrations() -> list[dict]:
    """Return the saved sheet placements without exposing store internals."""
    with _LOCK:
        return _state()['registrations']


def set_registration(source_id, page, level, reg) -> None:
    if not isinstance(reg, dict):
        raise ValueError('A registration must be an object.')
    with _LOCK:
        row = _state()
        _source_page(row, source_id, page)
        row['registrations'] = [r for r in row['registrations']
                                if (r['source'], r['page'], r['level']) != (source_id, page, level)]
        row['registrations'].append({'source': source_id, 'page': page,
                                     'level': deepcopy(level), 'reg': deepcopy(reg)})
        _save(row)


def registration(source_id, page, level) -> dict | None:
    with _LOCK:
        return next((r['reg'] for r in _state()['registrations']
                     if (r['source'], r['page'], r['level']) == (source_id, page, level)), None)


def page_image(source_id, page) -> bytes:
    """Return the model-sized PNG for the sheet underlay."""
    with _LOCK:
        source = _source_page(_state(), source_id, page)
        if source['kind'] != 'drawing':
            raise ValueError('A sheet must be a drawing source.')
        return (Path(DATA_DIR) / 'sources' / source['id'] / f'{page}.png').read_bytes()


def master_size(source_id, page):
    """Read only the PNG signature and IHDR; legacy masters stay lazy."""
    with _LOCK:
        source = _source_page(_state(), source_id, page)
        target = Path(DATA_DIR) / 'sources' / source['id'] / f'master-{page}.png'
        try:
            with target.open('rb') as file:
                header = file.read(24)
            if len(header) != 24 or header[:16] != b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR':
                return None
            width, height = struct.unpack('>II', header[16:24])
            return [width, height] if 0 < width <= 7200 and 0 < height <= 7200 else None
        except OSError:
            return None


def _master_image(source_id, page) -> Image.Image:
    """Backfill pre-master uploads without holding the store lock while rendering."""
    with _LOCK:
        # Validate first so invalid/unhashable source or page values still raise ValueError.
        _source_page(_state(), source_id, page)
        key = (source_id, page)
        page_lock = _MASTER_LOCKS.get(key)
        if page_lock is None:
            page_lock = threading.Lock()
            _MASTER_LOCKS[key] = page_lock
    with page_lock:
        with _LOCK:
            row = _state()
            source = _source_page(row, source_id, page)
            if source['kind'] != 'drawing':
                raise ValueError('A sheet must be a drawing source.')
            root = Path(DATA_DIR) / 'sources' / source['id']
            target = root / f'master-{page}.png'
            source_generation = row['generation']
            cached = target.read_bytes() if target.is_file() else None
        if cached is not None:
            try:
                image = Image.open(io.BytesIO(cached))
                try:
                    image.load()  # Detect truncated pixel data as well as invalid headers.
                except Exception:
                    image.close()
                    raise
                return image
            except (OSError, SyntaxError, ValueError):
                with LIFECYCLE, _LOCK:
                    if source_generation != _state()['generation']:
                        raise StaleGeneration('The house was started over while reading the sheet.')
                    target.unlink(missing_ok=True)
        with _LOCK:
            if source_generation != _state()['generation']:
                raise StaleGeneration('The house was started over while reading the sheet.')
            pdf = (root / 'original.pdf').read_bytes()
        image = twin_pdf.render_page(pdf, page, dpi=300, max_side=7200, grayscale=True)
        try:
            _write_master(target, image, source_generation)
        except Exception:
            image.close()
            raise
        return image


def crop(source_id, page, box, max_side=2048) -> dict:
    """Crop the full-resolution sheet, shrinking only when needed for the caller."""
    box = _box(box)
    if type(max_side) is not int or max_side <= 0:
        raise ValueError('The crop size limit must be a positive integer.')
    with _master_image(source_id, page) as master:
        width, height = master.size
        bounds = (math.floor(box[0] * width), math.floor(box[1] * height),
                  math.ceil(box[2] * width), math.ceil(box[3] * height))
        with master.crop(bounds) as image:
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            with io.BytesIO() as output:
                image.save(output, format='PNG')
                return {'mime': 'image/png', 'b64': base64.b64encode(output.getvalue()).decode('ascii'),
                        'box': box, 'size': list(image.size), 'master': [width, height]}


def crop_to_master(crop, uv) -> list:
    """Map crop-normalised coordinates to pixels in the full-resolution master."""
    x0, y0, x1, y1 = crop['box']
    width, height = crop['master']
    return [(x0 + uv[0] * (x1 - x0)) * width,
            (y0 + uv[1] * (y1 - y0)) * height]


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
                path, mime = root / 'model.jpg', 'image/jpeg'
                if not path.is_file():  # Sources uploaded before model derivatives existed.
                    mime = source['mime']
                    path = root / ('original.png' if mime == 'image/png' else 'original.jpg')
            images.append({'mime': mime, 'b64': base64.b64encode(path.read_bytes()).decode('ascii')})
        return images
