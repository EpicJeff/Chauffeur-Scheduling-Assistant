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


DIRECTOR_PROMPT = """Act as the household's architectural art director. Compare
the labelled renders with the household photos and the kit's style guide.
Return JSON only: {"critique": "specific assessment and changes", "done": false,
"site": {...}, "materials": {...}}. Return complete revised site and materials
objects, preserving their schema, IDs and compose provenance. All distances are
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
    allowed = {value['asset'] for value in kit['materials'].values()}
    for role, value in list(revised['materials'].items()):
        asset_id = value.get('id') if isinstance(value, dict) else value
        if role not in kit['materials']:
            del revised['materials'][role]
            notes.append(f'Ignored material role {role} with asset {asset_id}: not in the kit.')
        elif not isinstance(asset_id, str) or asset_id not in allowed:
            default = kit['materials'][role]
            revised['materials'][role] = deepcopy(current['materials'].get(
                role, {'id': default['asset'], 'color': default['color']}))
            notes.append(f'Refused material {asset_id} for {role}; kept its current value or kit default.')
    presets = set(kit['shrubs'] + kit['backdrop_trees'] + kit['specimen_trees'])
    furniture = {'polyhaven:' + value for value in kit['furniture'].values()}
    for name, field, accepted in (('planting', 'preset', presets), ('furniture', 'asset', furniture)):
        items = revised['site'].get(name, [])
        if not isinstance(items, list):
            continue  # normalize supplies a note for an invalid list
        kept = []
        for item in items:
            asset_id = item.get(field) if isinstance(item, dict) else None
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
        _validate(run, renders, cameras, base)
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
            return None, str(answer['error'])
        if (not isinstance(answer.get('critique'), str) or type(answer.get('done')) is not bool
                or not isinstance(answer.get('site'), dict)
                or not isinstance(answer.get('materials'), dict)):
            return None, 'The art director must return critique, done, site and materials.'
        notes = []
        revised = _enforce_kit(answer, current, kit, notes)
        plan, normalized_notes = twin_plan.merge_director(current, revised)
        notes.extend(normalized_notes)
        cost = math.fsum(entry['usd'] for entry in entries)
        round_id = twin_store.push_round(plan, 'director', note=answer['critique'][:200],
                                         cost=cost, run=run, base=base)
        saved = next(r for r in twin_store.rounds() if r['id'] == round_id)
        return {'round': round_id, 'critique': answer['critique'], 'done': answer['done'],
                'plan': twin_store.current(), 'cost': cost, 'stale': saved['stale'], 'notes': notes}, None
    except twin_cost.CheckpointReached:
        raise
    except Exception as exc:
        logger.exception('Twin director %s failed', run)
        return None, str(exc)
    finally:
        _LOCK.release()
