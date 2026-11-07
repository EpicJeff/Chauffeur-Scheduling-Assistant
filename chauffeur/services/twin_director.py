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
Omitted site keys and material roles are unchanged; only explicit [] or null
deletes. Material values must be {"id":"kit_asset", "color":"#rrggbb"}.
All distances are
feet. Change only site and materials, never buildings, openings or roof geometry.
Use only the supplied kit's material IDs, plant presets and furniture assets.
Respect its composition values, clearances and the household's real finishes.
Set done true when the render meets the brief without further changes.
"""

_LOCK = threading.Lock()
logger = logging.getLogger(__name__)


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
    for role, value in list(revised['materials'].items()):
        if role in current['materials'] and value == current['materials'][role]:
            continue
        asset_id = value.get('id') if isinstance(value, dict) else value
        if role not in kit['materials']:
            del revised['materials'][role]
            notes.append(f'Ignored material role {role} with asset {asset_id}: not in the kit.')
        else:
            validation_notes = []
            validated = _draft_materials({'materials': {role: value}}, kit, validation_notes)
            if not validation_notes:
                revised['materials'][role] = validated[role]
                continue
            default = kit['materials'][role]
            revised['materials'][role] = deepcopy(current['materials'].get(
                role, {'id': default['asset'], 'color': default['color']}))
            notes.append(f'Refused invalid material {asset_id} or colour for {role}; '
                         'kept its current value or kit default.')
    presets = set(kit['shrubs'] + kit['backdrop_trees'] + kit['specimen_trees'])
    furniture = {value.removeprefix('polyhaven:') for value in kit['furniture'].values()}
    for name, field, accepted in (('planting', 'preset', presets), ('furniture', 'asset', furniture)):
        items = revised['site'].get(name, [])
        if not isinstance(items, list):
            continue  # normalize supplies a note for an invalid list
        kept = []
        old_items = current['site'].get(name, [])
        for item in items:
            if isinstance(item, dict) and item.get('id') is not None:
                unchanged = any(old.get('id') == item['id'] and old == item
                                for old in old_items if isinstance(old, dict))
            else:
                unchanged = item in old_items
            if unchanged:
                kept.append(item)
                continue
            asset_id = item.get(field) if isinstance(item, dict) else None
            if name == 'furniture' and isinstance(item, dict):
                kind = item.get('kind')
                asset_id = asset_id or (kit['furniture'].get(kind) if isinstance(kind, str) else None)
                if isinstance(asset_id, str):
                    asset_id = asset_id.removeprefix('polyhaven:')
            if not isinstance(asset_id, str) or asset_id not in accepted:
                notes.append(f'Dropped off-kit {name} {asset_id}.')
            else:
                kept.append(item)
        revised['site'][name] = kept
    return revised


def critique(run: str, renders: list[str], cameras: list[str], base: int | None = None
             ) -> tuple[dict | None, str | None]:
    if not _LOCK.acquire(blocking=False):
        return None, 'a critique is already running'
    try:
        try:
            _validate(run, renders, cameras, base)
        except ValueError as exc:
            return None, str(exc)
        if sum(r['kind'] == 'director' and r.get('run') == run
               for r in twin_store.rounds()) >= twin_cost.ROUND_CAP:
            return None, 'round cap reached'
        settings = storage.get_settings()
        _, key = model_pools.credentials('twin', settings)
        if not key:
            return None, 'No model key is configured for twin art direction.'
        # Keep the base tied to the snapshot even for direct callers omitting it.
        snapshot_id = twin_store.current_id()
        current = twin_store.current()
        if current is None:
            return None, 'Save a house plan before running the art director.'
        if base is None:
            base = snapshot_id
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
                + '\nCurrent materials: ' + json.dumps(current['materials']))
        images.extend({'mime': 'image/png', 'b64': render} for render in renders)
        usage = []
        twin_cost.require_clear()
        try:
            answer = model_pools.call_pool_json(
                'twin', key, DIRECTOR_PROMPT, user, images=images, strict_json=True,
                max_models=1, max_output_tokens=16384, timeout_s=180, usage=usage)
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
        revised, notes = twin_plan.overlay_director(current, answer)
        revised = _enforce_kit(revised, current, kit, notes)
        plan, normalized_notes = twin_plan.normalize(twin_plan.record_compose_overrides(current, revised))
        notes.extend(normalized_notes)
        cost = math.fsum(entry['usd'] for entry in entries)
        round_id = twin_store.push_round(plan, 'director', note=answer['critique'][:200],
                                         cost=cost, run=run, base=base)
        saved = next(r for r in twin_store.rounds() if r['id'] == round_id)
        return {'round': round_id, 'critique': answer['critique'], 'done': answer['done'],
                'plan': twin_store.current(), 'cost': cost, 'stale': saved['stale'], 'notes': notes}, None
    except twin_cost.CheckpointReached:
        raise
    except ValueError:
        return None, 'The art director returned an invalid house plan.'
    except Exception:
        logger.exception('Twin director %s failed', run)
        return None, 'The art director could not finish. Please try again.'
    finally:
        _LOCK.release()
