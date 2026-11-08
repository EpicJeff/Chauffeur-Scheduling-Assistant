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

from services import storage, twin_pdf, twin_plan, twin_place

DATA_DIR = os.path.join(os.path.dirname(storage.DB_PATH), 'twin')
_LOCK = threading.RLock()
LIFECYCLE = threading.RLock()
_MASTER_LOCKS = weakref.WeakValueDictionary()  # Only active page readers retain locks.
build_running = lambda: False  # Task 8 supplies the build runner's predicate.
stop_builds_for_start_over = lambda: None
_KINDS = {'draft', 'director', 'hand', 'revert', 'build', 'edit', 'start_over'}
_PAGE_ROLES = set(twin_place.BUILDING_ROLES) | set(twin_place.LOT_ROLES)
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


def _place(row):
    """Migrate a private state snapshot; caller holds _LOCK and saves on success."""
    if 'place' not in row:
        plan = _read_round(row, row['current']) if row['current'] is not None else None
        row['place'] = twin_place.migrate(row, plan)
        for source in row['sources']:
            if source['kind'] == 'drawing' and source.get('part') is None:
                pages = [p for p in row['page_roles'] if p['source'] == source['id']]
                source['part'] = next((p.get('building', 'house') for p in pages if p['role'] != 'plot'),
                                      twin_place.LOT if pages else 'house')
        for page in row['page_roles']:
            if page['role'] == 'plot':
                page['building'] = twin_place.LOT
            else:
                page.setdefault('building', 'house')
    return row['place']


def _place_state():
    row = _state()
    migrated = 'place' not in row
    _place(row)
    if _clear_plot_read(row) or migrated:
        _save(row)
    return row


def _plot_page(row):
    """The single confirmed plot region on the lot, including its provenance."""
    sources = {s['id'] for s in row['sources'] if s['kind'] == 'drawing'}
    pages = [p for p in row['page_roles'] if p['role'] == 'plot'
             and p.get('building') == twin_place.LOT and p['source'] in sources]
    if len(pages) != 1:
        return None
    return {key: deepcopy(pages[0].get(key)) for key in ('source', 'page', 'box')}


def _clear_plot_read(row):
    """Keep confirmed placement, but discard suggestions tied to an old page."""
    lot = _place(row)['lot']
    page = _plot_page(row)
    changed = False
    for key in ('read', 'placement'):
        value = lot.get(key)
        if value is None or (key == 'placement' and value.get('confirmed')):
            continue
        if {k: value.get(k) for k in ('source', 'page', 'box')} != page:
            lot[key] = None
            changed = True
    return changed


def place() -> dict:
    with _LOCK:
        return deepcopy(_place_state()['place'])


def _check_part(place, part):
    if not isinstance(part, str) or (
            part != twin_place.LOT and not any(b['id'] == part for b in place['buildings'])):
        raise ValueError('Choose a part of your place.')


def _building_name(place, name, bid=None):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError('Give the building a name of at most 100 characters.')
    name = name.strip()
    if any(b['id'] != bid and b['name'].casefold() == name.casefold() for b in place['buildings']):
        raise ValueError(f'There is already a building called {name}.')
    return name


def _check_building_kind(kind):
    if not isinstance(kind, str) or kind not in twin_place.KINDS:
        raise ValueError('Choose a kind of building.')


def _add_building(place, bid, name, kind):
    building = {'id': bid, 'name': name, 'kind': kind, 'footprint': None,
                'footprint_from': None, 'shell': twin_place.shell_for(kind), 'shell_from': 'default'}
    place['buildings'].append(building)
    return building


def _legacy_house(place, bid='house'):
    kind = {'house': 'main_house', 'pool_house': 'pool_house'}.get(bid) if isinstance(bid, str) else None
    if kind and not any(b['id'] == bid for b in place['buildings']):
        _add_building(place, bid, twin_place.KINDS[kind], kind)


def add_building(name: str, kind: str) -> dict:
    with _LOCK:
        row = _state()
        registry = _place(row)
        name = _building_name(registry, name)
        _check_building_kind(kind)
        bid = twin_place.new_id(name, {b['id'] for b in registry['buildings']})
        building = _add_building(registry, bid, name, kind)
        _save(row)
        return deepcopy(building)


def _update_place_building(row, bid, fields):
    """Validate and update only the private snapshot, shared with hand edits."""
    registry = _place(row)
    building = next((b for b in registry['buildings'] if b['id'] == bid), None)
    if building is None:
        raise ValueError('Choose a building in your place.')
    allowed = {'name', 'kind', 'shell', 'shell_from', 'footprint', 'footprint_from'}
    if not isinstance(fields, dict) or fields.keys() - allowed:
        raise ValueError('Choose a building detail to change.')
    checked = deepcopy(building)
    if 'name' in fields:
        checked['name'] = _building_name(registry, fields['name'], bid)
    if 'kind' in fields:
        _check_building_kind(fields['kind'])
        checked['kind'] = fields['kind']
    if 'shell' in fields:
        if not isinstance(fields['shell'], dict):
            raise ValueError('A shell needs its dimensions and roof shape.')
        checked['shell'] = twin_place.check_shell({**building['shell'], **fields['shell']})
        checked['shell_from'] = fields.get('shell_from', 'person')
    if 'shell_from' in fields and ('shell' not in fields or fields['shell_from'] not in ('person', 'photos')):
        raise ValueError('Shell dimensions must come from a person or photos.')
    if 'footprint' in fields:
        checked['footprint'] = twin_place.check_footprint(fields['footprint'])
    if 'footprint_from' in fields:
        if fields['footprint_from'] not in ('plot', 'typed', 'drawn'):
            raise ValueError('A footprint must come from a plot, typed points or a drawing.')
        checked['footprint_from'] = fields['footprint_from']
    building.update(checked)
    return building


def update_building(bid: str, fields: dict) -> dict:
    with LIFECYCLE, _LOCK:
        row = _state()
        registry = _place(row)
        old = next((deepcopy(b) for b in registry['buildings'] if b['id'] == bid), None)
        building = _update_place_building(row, bid, fields)
        plan = _read_round(row, row['current']) if row['current'] is not None else None
        if (plan is not None and any(b['id'] == bid for b in plan['buildings'])
                and any(old[key] != building[key] for key in ('name', 'kind'))):
            def rename(current):
                target = next(b for b in current['buildings'] if b['id'] == bid)
                if old['name'] != building['name']:
                    target['name'] = building['name']
                if 'kind' in fields:
                    target['kind'] = building['kind']
                return current

            note = (f'Renamed {old["name"]} to {building["name"]}' if old['name'] != building['name']
                    else f'Changed {building["name"]} to {twin_place.KINDS[building["kind"]]}')
            update_current(rename, kind='edit', note=note)
            latest = _state()
            latest['place'], latest['page_roles'], latest['sources'] = registry, row['page_roles'], row['sources']
            row = latest
        _save(row)
        return deepcopy(building)


def remove_building(bid: str) -> None:
    with LIFECYCLE, _LOCK:
        row = _state()
        registry = _place(row)
        if not any(b['id'] == bid for b in registry['buildings']):
            raise ValueError('Choose a building in your place.')
        if (any(p['building'] == bid for p in row['page_roles'])
                or any(s['kind'] == 'drawing' and s.get('part') == bid for s in row['sources'])):
            raise ValueError('Move or remove this building\'s pages first.')
        plan = _read_round(row, row['current']) if row['current'] is not None else None
        if plan is not None and any(b['id'] == bid for b in plan['buildings']):
            raise ValueError('This building is part of the house. Delete it from the house first.')
        registry['buildings'] = [b for b in registry['buildings'] if b['id'] != bid]
        for sid, parts in registry['photo_tags'].items():
            registry['photo_tags'][sid] = [part for part in parts if part != bid]
        for source in row['sources']:
            if source['kind'] == 'photo' and source.get('part') == bid:
                source['part'] = None
        _save(row)


def move_page(source: str, page: int, part: str, region: int | None = None) -> list[dict]:
    with _LOCK:
        row = _state()
        _check_part(_place(row), part)
        _source_page(row, source, page)
        moved = [p for p in row['page_roles'] if p['source'] == source and p['page'] == page]
        if not moved:
            item = {'source': source, 'page': page, 'building': part,
                    'role': 'other', 'level': None, 'box': None}
            row['page_roles'].append(item)
            moved = [item]
        if region is not None:
            if type(region) is not int or not 0 <= region < len(moved):
                raise ValueError('Choose a region on this page.')
            moved = [moved[region]]
        roles = twin_place.LOT_ROLES if part == twin_place.LOT else twin_place.BUILDING_ROLES
        for item in moved:
            item['building'] = part
            if item['role'] not in roles:
                item['role'], item['level'] = 'other', None
        _clear_plot_read(row)
        _save(row)
        return deepcopy(moved)


def set_photo_tags(source: str, parts: list[str]) -> list[str]:
    with _LOCK:
        row = _state()
        registry = _place(row)
        if not any(s['id'] == source and s['kind'] == 'photo' for s in row['sources']):
            raise ValueError('Choose a photo in your place.')
        if not isinstance(parts, list):
            raise ValueError('Choose the parts shown in this photo.')
        for part in parts:
            _check_part(registry, part)
        tags = list(dict.fromkeys(parts))
        registry['photo_tags'][source] = tags
        _save(row)
        return tags[:]


def photos_for(part: str) -> list[str]:
    with _LOCK:
        row = _place_state()
        registry = row['place']
        _check_part(registry, part)
        return [s['id'] for s in row['sources'] if s['kind'] == 'photo'
                and part in (registry['photo_tags'].get(s['id']) or [twin_place.LOT])]


def set_lot(lot: dict) -> None:
    if not isinstance(lot, dict):
        raise ValueError('The lot needs its placement and drawing read.')
    with _LOCK:
        row = _state()
        _place(row)['lot'] = deepcopy(lot)
        _save(row)


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
        _save({'generation': next_generation, 'place': twin_place.empty_place()})
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
    with LIFECYCLE, _LOCK:
        row = _state()
        if generation is not None and generation != row['generation']:
            raise StaleGeneration('The house was started over. Discard this result.')
        if kind not in _KINDS:
            raise ValueError('Unknown twin round kind.')
        _check_base(base)
        plan, _ = twin_plan.normalize(plan)
        return _append_round(row, plan, kind, note, cost, run, base, step=step)


def update_current(mutator, kind, note='', step=None, cost=None, generation=None, *, state_mutator=None) -> int:
    """Publish a latest-plan mutation and any paired state changes in one save."""
    with LIFECYCLE, _LOCK:
        row = _state()
        if generation is not None and generation != row['generation']:
            raise StaleGeneration('The house was started over. Discard this result.')
        if kind not in _KINDS:
            raise ValueError('Unknown twin round kind.')
        before = _read_round(row, row['current']) if row['current'] is not None else None
        plan, _ = twin_plan.normalize(mutator(before))
        if state_mutator is not None:
            state_mutator(row)
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
        plan = _read_round(row, round_id)
        _follow_place(row, plan)
        return _append_round(row, plan, 'revert')


def _follow_place(row, plan):
    """Reconcile a normalized whole-plan save in the same state mutation."""
    registry = _place(row)
    by_id = {b['id']: b for b in registry['buildings']}
    for migrated in twin_place.migrate({}, plan)['buildings']:
        if migrated['id'] not in by_id:
            registry['buildings'].append(migrated)
            by_id[migrated['id']] = migrated
    for building in plan['buildings']:
        record = by_id[building['id']]
        building['name'] = record['name']
        # Legacy plans have no kind field; retain that implicit representation.
        if 'kind' in building:
            building['kind'] = record['kind']


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
    with LIFECYCLE, _LOCK:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('A hand edit needs a reason.')
        _check_base(base)
        row = _state()
        if base is not None and base != row['current']:
            raise StaleRound('The twin has changed. Reload it before saving this edit.')
        before = _read_round(row, row['current']) if row['current'] is not None else None
        if before is not None:
            plan = twin_plan.record_compose_overrides(before, plan)
        normalized, _ = twin_plan.normalize(plan)
        _follow_place(row, normalized)
        # Keep raw geometry for the fix log, but log only accepted names/kinds.
        plan = deepcopy(plan)
        by_id = {b['id']: b for b in normalized['buildings']}
        for building in plan.get('buildings', []):
            if isinstance(building, dict) and building.get('id') in by_id:
                accepted = by_id[building['id']]
                building['name'] = accepted['name']
                if 'kind' in building:
                    building['kind'] = accepted['kind']
        # The first save establishes the plan; it corrects no previous leaves.
        # Log the person's edits before normalization drops dependent geometry
        # (e.g. an opening on a removed wall) and shifts positional list items.
        changes = [] if before is None else [
            {'path': path, 'kind': _fix_kind(path), 'before': _leaf(before, path), 'after': _leaf(plan, path),
             'reason': reason}
            for path in twin_plan.diff_paths(before, plan)
            if _fix_kind(path) is not None
        ]
        return _append_round(row, normalized, 'hand', note=reason, base=base, changes=changes)


def fixes() -> list[dict]:
    with _LOCK:
        return _state()['fixes']


def save_source(kind: str, filename: str, data: bytes, *, content_type: str | None = None,
                part: str | None = None) -> str:
    """Verify photos and render drawings before locking their storage writes."""
    if kind not in ('drawing', 'photo'):
        raise ValueError('A source must be a drawing or photo.')
    if not data:
        raise ValueError('The source is empty.')
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError('The source needs a filename.')
    with _LOCK:
        row = _state()
        if part is not None:
            registry = _place(row)
            _legacy_house(registry, part)
            _check_part(registry, part)
        source_generation = row['generation']
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
              'pages': len(pages) if kind == 'drawing' else 1, 'mime': mime,
              'part': 'house' if part is None and kind == 'drawing' else part}
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
            registry = _place(row)
            if part is not None:
                _legacy_house(registry, part)
                _check_part(registry, part)
            elif kind == 'drawing':
                _legacy_house(registry)
            if kind == 'photo':
                registry['photo_tags'][source_id] = ([part] if part is not None else
                                                    [*[b['id'] for b in registry['buildings']], twin_place.LOT])
            row['sources'].append(record)
            _save(row)
    except Exception:
        with LIFECYCLE, _LOCK:
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
        registry = _place(row)
        checked = []
        for item in rows:
            if not isinstance(item, dict):
                raise ValueError('A page role must be an object.')
            _source_page(row, item.get('source'), item.get('page'))
            if not isinstance(item.get('role'), str) or item['role'] not in _PAGE_ROLES:
                raise ValueError('Unknown page role.')
            building = item.get('building')
            if 'building' not in item:
                building = twin_place.LOT if item['role'] == 'plot' else 'house'
            _legacy_house(registry, building)
            _check_part(registry, building)
            roles = twin_place.LOT_ROLES if building == twin_place.LOT else twin_place.BUILDING_ROLES
            if item['role'] not in roles:
                raise ValueError('That page role does not fit this part of your place.')
            level = item.get('level')
            if level is not None and (not isinstance(level, str) or not level.strip() or len(level) > 80):
                raise ValueError('A level must be null or a non-empty string of at most 80 characters.')
            box = None if item.get('box') is None else _box(item['box'])
            checked.append({'source': item['source'], 'page': item['page'],
                            'role': item['role'], 'level': level,
                            'box': box, 'building': building})
        row['page_roles'] = checked
        _clear_plot_read(row)
        _save(row)


def page_roles() -> list[dict]:
    with _LOCK:
        return _state()['page_roles']


def registrations() -> list[dict]:
    """Return the saved sheet placements without exposing store internals."""
    with _LOCK:
        return _state()['registrations']


def _set_registration(row, source_id, page, level, reg):
    """Validate a registration into a private snapshot for a single publication."""
    if not isinstance(reg, dict):
        raise ValueError('A registration must be an object.')
    _source_page(row, source_id, page)
    row['registrations'] = [r for r in row['registrations']
                            if (r['source'], r['page'], r['level']) != (source_id, page, level)]
    row['registrations'].append({'source': source_id, 'page': page,
                                 'level': deepcopy(level), 'reg': deepcopy(reg)})


def set_registration(source_id, page, level, reg) -> None:
    with _LOCK:
        row = _state()
        _set_registration(row, source_id, page, level, reg)
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
    return twin_place.to_master(crop, uv)


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
