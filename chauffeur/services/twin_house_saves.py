"""Named house snapshots. Files retain references to Library assets and source images."""
import base64
from copy import deepcopy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import re
import uuid

from PIL import Image
from services import twin_model, twin_model_bridge, twin_plan, twin_place, twin_store as store

FORMAT = 'chauffeur-house'
VERSION = 1
MAX_BYTES = 20 * 1024 * 1024
MAX_THUMBNAIL_BYTES = 256 * 1024


def _invalid_number(value):
    raise ValueError('House JSON must use finite numbers.')


def name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 80:
        raise ValueError('Give the house a name from 1 to 80 characters.')
    return value.strip()


def filename(value):
    stem = re.sub(r'[^\w .-]', '-', value, flags=re.UNICODE).strip(' .') or 'House'
    return stem + '.chauffeur-house.json'


def _path(sid):
    if not isinstance(sid, str) or not re.fullmatch(r'[a-f0-9]{32}', sid):
        raise ValueError('No such saved house.')
    return Path(store.DATA_DIR) / 'houses' / f'{sid}.json'


def _read(sid):
    try:
        return json.loads(_path(sid).read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ValueError('No such saved house.') from exc


def _thumbnail(value):
    if value is None:
        return None
    prefix = 'data:image/png;base64,'
    if not isinstance(value, str) or not value.startswith(prefix) or len(value) > MAX_THUMBNAIL_BYTES * 4 // 3 + len(prefix) + 4:
        raise ValueError('The thumbnail must be a PNG of at most 256 KB.')
    try:
        data = base64.b64decode(value[len(prefix):], validate=True)
        if len(data) > MAX_THUMBNAIL_BYTES:
            raise ValueError()
        with Image.open(io.BytesIO(data)) as image:
            if image.format != 'PNG' or max(image.size) > 512:
                raise ValueError()
            image.verify()
    except (ValueError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError('The thumbnail must be a readable PNG, at most 512 pixels and 256 KB.') from exc
    return value


def _state(value):
    """Validate reference metadata without copying or fetching any source bytes."""
    if not isinstance(value, dict) or any(key not in value for key in store.HOUSE_STATE_KEYS):
        raise ValueError('The house file needs its place and source references.')
    value = {key: deepcopy(value[key]) for key in store.HOUSE_STATE_KEYS}
    place = value['place']
    if not isinstance(place, dict) or not isinstance(place.get('buildings'), list) or not isinstance(place.get('lot'), dict) or not isinstance(place.get('photo_tags'), dict):
        raise ValueError('The saved place needs buildings, lot and photo tags.')
    ids = set()
    for building in place['buildings']:
        if not isinstance(building, dict) or not isinstance(building.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', building['id']) or building['id'] in ids:
            raise ValueError('The saved place has an invalid building id.')
        ids.add(building['id'])
        store._building_name(place, building.get('name'), building['id'])
        store._check_building_kind(building.get('kind'))
        twin_place.check_shell(building.get('shell'))
        if building.get('footprint') is not None:
            twin_place.check_footprint(building['footprint'])
    bearing = place['lot'].get('front_bearing_deg', 180)
    if not twin_plan._number(bearing) or not 0 <= bearing < 360:
        raise ValueError('The saved front bearing must be from 0 to 359 degrees.')
    for key in ('placement', 'read'):
        if place['lot'].get(key) is not None and not isinstance(place['lot'][key], dict):
            raise ValueError('The saved lot placement and drawing read must be objects.')
    for parts in place['photo_tags'].values():
        if not isinstance(parts, list) or any(not isinstance(p, str) or p not in ids | {'lot'} for p in parts):
            raise ValueError('The saved photo tags must name parts of this place.')
    if any(not isinstance(value[k], list) for k in ('sources', 'page_roles', 'registrations')):
        raise ValueError('The saved source references must be lists.')
    sources = {}
    for source in value['sources']:
        if (not isinstance(source, dict) or not isinstance(source.get('id'), str)
                or not re.fullmatch(r'[a-f0-9]{32}', source['id']) or source.get('kind') not in ('drawing', 'photo')
                or type(source.get('pages')) is not int or not 1 <= source['pages'] <= 500
                or not isinstance(source.get('filename'), str)):
            raise ValueError('The saved house has an invalid source reference.')
        sources[source['id']] = source
    for key in ('page_roles', 'registrations'):
        for row in value[key]:
            if not isinstance(row, dict) or row.get('source') not in sources or type(row.get('page')) is not int or not 1 <= row['page'] <= sources[row['source']]['pages']:
                raise ValueError('The saved sheet references an unknown source page.')
            if key == 'page_roles':
                if row.get('role') not in store._PAGE_ROLES or row.get('building') not in ids | {'lot'}:
                    raise ValueError('The saved sheet needs a valid role and building.')
                if row.get('box') is not None:
                    store._box(row['box'])
            elif not isinstance(row.get('reg'), dict) or 'level' not in row:
                raise ValueError('The saved sheet registration is invalid.')
    return value


def _registration(reg):
    if (not isinstance(reg, dict) or not twin_plan._number(reg.get('scale')) or reg['scale'] <= 0
            or not twin_plan._number(reg.get('angle')) or not twin_plan._point(reg.get('origin_px'))
            or not twin_plan._point(reg.get('offset'))):
        raise ValueError('The saved sheet registration needs a positive scale and valid coordinates.')


def _normalize(document):
    if not isinstance(document, dict) or document.get('format') != FORMAT or type(document.get('format_version')) is not int or document['format_version'] != VERSION:
        raise ValueError('Choose a Chauffeur house file with format version 1.')
    model = document.get('model')
    if not isinstance(model, dict):
        raise ValueError('The house file needs a model object.')
    if model.get('schema') == twin_model.SCHEMA:
        model, notes = twin_model.normalize(model)
    elif model.get('schema') == 'chauffeur.twin.plan/2':
        plan, notes = twin_plan.normalize(model)
        model, bridge_notes = twin_model_bridge.assemble(plan)
        notes += bridge_notes
    else:
        raise ValueError('This house model schema is not supported.')
    state = _state(document.get('state'))
    for row in state['registrations']:
        _registration(row['reg'])
    lot = state['place']['lot']
    placement = lot.get('placement')
    if placement is not None:
        _registration(placement.get('registration'))
        outline = twin_place.check_footprint(placement.get('outline'))
        edge = placement.get('street_edge')
        if not isinstance(edge, list) or len(edge) != 2 or any(type(i) is not int or not 0 <= i < len(outline) for i in edge):
            raise ValueError('The saved lot placement needs a valid street edge.')
    read = lot.get('read')
    if read is not None:
        from services import twin_place_reads
        try:
            twin_place_reads.plot_read_record({key: read[key] for key in ('source', 'page', 'box')},
                                             read['crop'], read['fragment'], registration=read['registration'],
                                             edge=read['street_edge'])
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ValueError('The saved lot drawing read is invalid.') from exc
    # Place names own model names in the editor's normal mutation path too.
    before = [(b['id'], b.get('name'), b.get('kind')) for b in model['buildings']]
    store._follow_place(state, model)
    if before != [(b['id'], b.get('name'), b.get('kind')) for b in model['buildings']]:
        notes.append('Matched building names and kinds to the saved place.')
    return model, state, notes


def _metadata(document):
    return {key: deepcopy(document[key]) for key in ('id', 'name', 'created_at', 'created_by', 'size', 'summary', 'thumbnail')}


def _document(model, state, title, member, thumbnail=None):
    return {'format': FORMAT, 'format_version': VERSION, 'id': uuid.uuid4().hex,
            'name': name(title), 'created_at': datetime.now(timezone.utc).isoformat(),
            'created_by': member, 'model': model, 'state': state, 'thumbnail': _thumbnail(thumbnail),
            'summary': {'building_count': len(state['place']['buildings']),
                        'room_count': sum(len(b.get('rooms', [])) for b in model['buildings']) + len(model.get('site', {}).get('yard_rooms', []))}}


def _write(document):
    document['size'] = 0
    # Size includes the complete portable JSON, including this size field.
    for _ in range(4):
        document['size'] = len(json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8'))
    if document['size'] > MAX_BYTES:
        raise ValueError('House files may be at most 20 MB.')
    store.atomic_json(_path(document['id']), document)
    return _metadata(document)


def list_saves():
    with store.LIFECYCLE, store._LOCK:
        root = Path(store.DATA_DIR) / 'houses'
        return sorted((_metadata(_read(p.stem)) for p in root.glob('*.json')), key=lambda s: (s['created_at'], s['id']), reverse=True)


def current_document(title='Current house', member=None, thumbnail=None):
    with store.LIFECYCLE, store._LOCK:
        row = store._place_state()
        model = store.current_model()
        if model is None:
            raise ValueError('There is no house yet. Build or draw a house first.')
        document = _document(model, store.house_state(row), title, member, thumbnail)
        document['size'] = 0
        for _ in range(4):
            document['size'] = len(json.dumps(document, ensure_ascii=False, allow_nan=False).encode('utf-8'))
        return document


def save_current(title, member, thumbnail=None):
    with store.LIFECYCLE, store._LOCK:
        return _write(current_document(title, member, thumbnail))


def download(sid=None):
    with store.LIFECYCLE, store._LOCK:
        return _read(sid) if sid is not None else current_document()


def upload(data, member):
    if len(data) > MAX_BYTES:
        raise ValueError('House files may be at most 20 MB.')
    try:
        document = json.loads(data, parse_constant=_invalid_number)
        model, state, notes = _normalize(document)
        title = name(document.get('name'))
        picture = _thumbnail(document.get('thumbnail'))
    except (UnicodeError, json.JSONDecodeError, RecursionError, TypeError, KeyError, AttributeError, IndexError, OverflowError) as exc:
        raise ValueError('The house file is not valid Chauffeur house JSON.') from exc
    with store.LIFECYCLE, store._LOCK:
        return {'save': _write(_document(model, state, title, member, picture)), 'notes': notes}


def rename(sid, title):
    with store.LIFECYCLE, store._LOCK:
        document = _read(sid)
        document['name'] = name(title)
        return _write(document)


def delete(sid):
    with store.LIFECYCLE, store._LOCK:
        _read(sid)
        _path(sid).unlink()
        return {'deleted': True}


def load(sid):
    with store.LIFECYCLE, store._LOCK:
        if store.build_running():
            raise ValueError('Stop the build before loading a saved house.')
        document = _read(sid)
        model, state, notes = _normalize(document)
        row = store._place_state()
        # Old rounds predate place snapshots; capture the actual current place
        # too, since bearing and setup changes need not have made a round.
        if row['current'] is not None:
            store.atomic_json(store.round_state_path(row['current']), store.house_state(row))
        row.update(state)
        round_id = store._append_round(row, model, 'load', note=f'Loaded "{document["name"]}"')
        return {'round': round_id, 'notes': notes}
