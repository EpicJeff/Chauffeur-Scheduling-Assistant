"""One metered art-direction round; geometry and newer hand edits win."""
import base64
from copy import deepcopy
import io
import json
import logging
import math
import re
import threading

from PIL import Image

from services import model_pools, storage, twin_cost, twin_library, twin_plan, twin_store
from services.twin_draft import _materials as _draft_materials


DIRECTOR_PROMPT = """Act as the household's architectural art director. Compare
the labelled renders with the household photos and the kit's style guide.
Return JSON only: {"critique": "specific assessment and changes", "done": false,
"site": {...}, "materials": {...}}. Preserve schema, IDs and compose provenance.
Top-level site or materials that is omitted, null or [] means unchanged.
Only ADD new plants, beds, edge planting and furniture, at most 25 total.
Never echo, edit, move, hide, reorder or remove existing pieces. Never edit other
site keys. To change or remove anything, describe it in critique; it will be
offered as a suggestion and is not applied. Omitted pieces mean nothing.
New pieces may omit id; any supplied id must be new. Use ordinary editor fields
only, with no provenance, state, visibility or device fields. Stay inside the lot,
use positive sizes and valid non-degenerate geometry, and avoid duplicate positions.
Use only the kit's plant presets and furniture assets. Omitted material roles are unchanged;
explicit [] or null deletes that material role.
Material values must be {"id":"kit_asset", "color":"#rrggbb"}.
All distances are
feet. Change only site and materials, never buildings, openings or roof geometry.
Use only the supplied kit's material IDs, plant presets and furniture assets.
Respect its composition values, clearances and the household's real finishes.
Set done true when the render meets the brief without further changes.
"""

_LOCK = threading.Lock()
logger = logging.getLogger(__name__)
MAX_REQUEST_B64 = 18 * 1024 * 1024


def _validate(run, renders, cameras, base):
    if not isinstance(run, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run):
        raise ValueError('Invalid twin director run id.')
    if (not isinstance(renders, list) or not 1 <= len(renders) <= 6
            or not isinstance(cameras, list) or len(renders) != len(cameras)
            or any(not isinstance(c, str) or not c.strip() for c in cameras)):
        raise ValueError('Provide one to six PNG renders with matching camera labels.')
    if base is not None and (type(base) is not int or base < 1):
        raise ValueError('The base must be a round id.')
    for render in renders:
        if isinstance(render, str) and len(render) > 4 * 1024 * 1024:
            raise ValueError('Each render must be at most 4 MB of base64.')
        try:
            if not isinstance(render, str):
                raise ValueError()
            data = base64.b64decode(render, validate=True)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != 'PNG':
                    raise ValueError()
                image.verify()
        except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
            raise ValueError('Each render must be a readable base64 PNG.') from exc


def _enforce_kit(revised, current, kit, notes):
    revised = deepcopy(revised)
    for role, value in list(revised.get('materials', {}).items()):
        if role in current.get('materials', {}) and value == current['materials'][role]:
            continue
        asset_id = value.get('id') if isinstance(value, dict) else value
        if role not in kit['materials']:
            if role in current.get('materials', {}):
                revised['materials'][role] = deepcopy(current['materials'][role])
            else:
                del revised['materials'][role]
            notes.append(f'Refused material role {role} with asset {asset_id}: not in the kit; kept its stored choice unchanged.')
        else:
            validation_notes = []
            validated = _draft_materials({'materials': {role: value}}, kit, validation_notes)
            if not validation_notes:
                revised['materials'][role] = validated[role]
                continue
            if role in current.get('materials', {}):
                revised['materials'][role] = deepcopy(current['materials'][role])
            else:
                del revised['materials'][role]
            notes.append(f'Refused invalid material {asset_id} or colour for {role}; '
                         'kept its stored choice unchanged.')
    positions = {_position(p) for value in current['site'].values()
                 for p in (value if isinstance(value, list) else [value]) if isinstance(p, dict)} - {None}
    ids = twin_plan.director_piece_ids(current)
    additions = 0
    for name in twin_plan.DIRECTOR_LISTS:
        old = current['site'].get(name, [])
        candidates = revised['site'].get(name, [])[len(old):]
        revised['site'][name] = deepcopy(old)
        for raw in candidates:
            try:
                if additions >= 25:
                    raise ValueError('at most 25 additions are allowed per round')
                if len(revised['site'][name]) >= twin_plan.CAPS.get(name, math.inf):
                    raise ValueError(f'the {name} collection is full (limit {twin_plan.CAPS[name]})')
                if 'id' in raw and (not isinstance(raw['id'], str)
                        or not re.fullmatch(r'[A-Za-z0-9_.:~-]{1,64}', raw['id']) or raw['id'] in ids):
                    raise ValueError('use a new piece id')
                piece = _ordinary_addition(name, raw, revised['site'], kit, notes)
                if piece['id'] in ids:
                    raise ValueError('use a new piece id')
                position = _position(piece)
                if position is None or position in positions:
                    raise ValueError('that position already has a piece or has no usable geometry')
                revised['site'][name].append(piece)
                ids.add(piece['id'])
                positions.add(position)
                additions += 1
            except Exception as exc:
                notes.append(f'Refused a new {name} piece: {str(exc).rstrip(".")}.')
    return revised


def _position(piece):
    for key in ('at', 'polygon', 'points', 'polyline'):
        if key in piece:
            try:
                points = [piece[key]] if key == 'at' else piece[key]
                return ('point' if key == 'at' else 'outline', tuple(sorted(tuple(float(v) for v in p) for p in points)))
            except (TypeError, ValueError):
                return None
    return None


def _ordinary_addition(name, raw, site, kit, notes):
    from services import twin_model_ops, twin_objects, twin_site_shapes, twin_terrain
    forbidden = {'by', 'src', 'read_geometry', 'state', 'confidence', 'visible_in', 'device', 'entity'}
    for key in forbidden.intersection(raw):
        value = raw[key]
        expected = {'by': str, 'src': dict, 'read_geometry': dict, 'state': str,
                    'confidence': (int, float), 'visible_in': list, 'device': str, 'entity': str}[key]
        if not isinstance(value, expected) or key == 'confidence' and (
                type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError(f'use a valid {key} value')
        if key == 'visible_in':
            twin_objects.validate(key, value, twin_objects.SCHEMA['common'][key])
    if forbidden.intersection(raw):
        notes.append(f'Ignored generator, visibility or device fields on a new {name} piece.')
    values = {k: deepcopy(v) for k, v in raw.items() if k not in forbidden}
    if name in ('planting', 'furniture'):
        properties = set(twin_objects.fields({}, name)) - {'visible_in'}
        if set(values) - (properties | {'id', 'at', 'preset', 'asset', 'kind'}):
            raise ValueError('use supported editor object fields')
        if name == 'planting':
            asset = values.get('preset', values.get('asset'))
            if not isinstance(asset, str) or asset not in kit['shrubs'] + kit['backdrop_trees'] + kit['specimen_trees']:
                raise ValueError(f'choose a kit plant preset, not {asset}')
            if 'asset' in values and values['asset'] != asset:
                raise ValueError(f'choose the same kit plant asset as the preset, not {values["asset"]}')
            kind = 'shrub' if asset in kit['shrubs'] else 'tree'
            if 'kind' in values and values['kind'] != kind:
                raise ValueError('choose the plant kind belonging to its preset')
        else:
            if 'preset' in values:
                raise ValueError('furniture uses a library asset')
            kind = values.get('kind')
            if kind is not None and (not isinstance(kind, str) or kind not in kit['furniture']):
                raise ValueError('choose a kit furniture kind')
            asset = values.get('asset') if 'asset' in values else kit['furniture'].get(kind)
            if not isinstance(asset, str) or asset.removeprefix('polyhaven:') not in kit['furniture'].values():
                raise ValueError(f'choose a kit furniture asset, not {asset}')
            asset = 'polyhaven:' + asset.removeprefix('polyhaven:')
            if twin_library.manifest().get(asset.removeprefix('polyhaven:'), {}).get('kind') != 'model':
                raise ValueError('choose an available library furniture model')
        op = {k: v for k, v in values.items() if k in properties | {'id', 'at'}}
        op.update(op='add_site_item', list=name, asset=asset, require_inside=True)
    else:
        allowed = {'id', 'polygon', 'points', 'polyline', 'material', 'materials', 'rotation', 'elevation'}
        if set(values) - allowed:
            raise ValueError('use supported editor drawing fields')
        # The editor's shape validator also supports existing line edge planting.
        if name == 'edges' and 'polygon' not in values:
            piece = {k: v for k, v in values.items() if k != 'id'}
            piece.setdefault('material', 'lawn')
            twin_site_shapes.validate(name, piece)
            geometry = 'points' if 'points' in piece else 'polyline'
            twin_site_shapes.update(name, piece, deepcopy(piece), site.get('lot'), require_inside=True)
            piece['id'] = twin_model_ops._create_id(site, name, values)
            piece['src'] = {'person': True}
            return piece
        op = {**values, 'op': 'add_site_shape', 'list': name, 'require_inside': True}
    model = {'site': deepcopy(site)}
    twin_model_ops._site_op(model, op, 'person', _batch_inplace=True)
    piece = model['site'][name][-1]
    if 'at' in piece and site.get('lot') and not twin_terrain.inside(site['lot'], piece['at']):
        raise ValueError('keep the piece inside the lot')
    return piece


def critique(run: str, renders: list[str], cameras: list[str], base: int | None = None
             ) -> tuple[dict | None, str | None]:
    generation = twin_store.generation()
    if not _LOCK.acquire(blocking=False):
        return None, 'a critique is already running'
    try:
        try:
            _validate(run, renders, cameras, base)
        except ValueError as exc:
            return None, str(exc)
        if twin_store.director_round_count(run) >= twin_cost.ROUND_CAP:
            return None, 'round cap reached'
        settings = storage.get_settings()
        # Keep the base tied to the snapshot even for direct callers omitting it.
        snapshot_id = twin_store.current_id()
        current = twin_store.current_model()
        if current is None:
            return None, 'Save a house plan before running the art director.'
        if base is None:
            base = snapshot_id
        if current.get('materials', {}) is None or any(
                current['site'].get(name, []) is None for name in twin_plan.DIRECTOR_LISTS):
            return {'round': snapshot_id, 'critique': 'Kept your saved yard unchanged.', 'done': False,
                    'plan': twin_store.current(), 'cost': 0, 'stale': base != snapshot_id,
                    'notes': ['No art director call was made. Nothing was saved.']}, None
        _, key = model_pools.credentials('twin', settings)
        if not key:
            return None, 'No model key is configured for twin art direction.'
        kit = twin_library.kit('modern_farmhouse')
        photos = [source for source in reversed(twin_store.sources()) if source['kind'] == 'photo'][:4]
        images = [image for source in photos for image in twin_store.source_images(source['id'])]
        user = (kit['style_guide'] + '\nKit composition: ' + json.dumps(kit['composition'])
                + '\nAllowed material assets and role defaults: ' + json.dumps(kit['materials'])
                + '\nAllowed plant presets: ' + json.dumps({name: kit[name] for name in
                    ('shrubs', 'backdrop_trees', 'specimen_trees')})
                + '\nAllowed furniture assets: ' + json.dumps(['polyhaven:' + value
                    for value in kit['furniture'].values()])
                + f'\nFirst {len(images)} images: household photos, newest first.'
                + '\nFollowing renders in image order: ' + json.dumps(cameras)
                + '\nCurrent site: ' + json.dumps(current['site'])
                + '\nCurrent materials: ' + json.dumps(current.get('materials', {})))
        images.extend({'mime': 'image/png', 'b64': render} for render in renders)
        if sum(len(image['b64']) for image in images) > MAX_REQUEST_B64:
            return None, 'The art director exceeds the 18 MiB image base64 budget.'
        usage = []
        twin_cost.require_clear()
        try:
            answer = model_pools.call_pool_json(
                'twin', key, DIRECTOR_PROMPT, user, images=images, strict_json=True,
                max_models=1, thinking_level='low', max_output_tokens=32768,
                timeout_s=180, usage=usage)
        finally:
            entries = twin_cost.record('director', usage, run)
        if not isinstance(answer, dict):
            return None, 'The art director returned invalid JSON.'
        if 'error' in answer:
            return None, 'The art director could not finish. Please try again.'
        if (not isinstance(answer.get('critique'), str) or type(answer.get('done')) is not bool
                or any(name in answer and answer[name] is not None
                       and answer[name] != [] and not isinstance(answer[name], dict)
                       for name in ('site', 'materials'))):
            return None, 'The art director must return critique, done and valid site/material edits.'
        notes = []
        def add_to_current(model):
            # The store supplies the latest connected house under its lock.
            # Only the four yard lists and material roles are changed here.
            revised, suggestions = twin_plan.overlay_director(model, answer)
            notes.extend(suggestions)
            return _enforce_kit(revised, model, kit, notes)
        cost = math.fsum(entry['usd'] for entry in entries)
        round_id = twin_store.update_model(add_to_current, 'director', note=answer['critique'][:200],
                                           cost=cost, run=run, base=base, generation=generation)
        if round_id is None:
            notes.append('No new pieces or material changes were applied. Nothing was saved.')
            round_id = twin_store.current_id()
            stale = base != round_id
        else:
            saved = next(r for r in twin_store.rounds() if r['id'] == round_id)
            stale = saved['stale']
        return {'round': round_id, 'critique': answer['critique'], 'done': answer['done'],
                'plan': twin_store.current(), 'cost': cost, 'stale': stale, 'notes': notes}, None
    except twin_cost.CheckpointReached:
        raise
    except twin_plan.DirectorUnsafe as exc:
        return None, str(exc)
    except ValueError:
        return None, 'The art director returned an invalid house plan.'
    except Exception:
        logger.exception('Twin director %s failed', run)
        return None, 'The art director could not finish. Please try again.'
    finally:
        _LOCK.release()
