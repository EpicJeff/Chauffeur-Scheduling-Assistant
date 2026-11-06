"""Three metered, resumable foreground calls to draft a household twin."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import threading
import uuid

from services import (ha_api, model_pools, storage, twin_compose, twin_cost,
                      twin_library, twin_plan, twin_store)


_RULES = """
All lengths and coordinates are in feet (units: ft); roof pitch is rise per 12.
Axes: x left to right seen from the front, y from the front wall to the rear,
z up. Points [x,y] are horizontal; elevation, sill and head describe z.
return only what the drawings show; omit what you cannot read
Return only the requested JSON fragment, with no prose or Markdown.
"""

BUILDING_PROMPT = """Read the drawing pages and return {"buildings": [...]}.
Each building uses this schema (optional details may be omitted):
{
  "id": "building_id", "name": "Building name", "position": [0,0],
  "levels": [{"id":"L1", "name":"Ground floor", "elevation":0, "ceiling":10}],
  "walls": [{"id":"front", "level":"L1", "from":[0,0], "to":[30,0],
             "height":10, "thickness":0.5, "exterior":true}],
  "openings": [{"wall":"front", "kind":"door", "at":5, "width":3,
                "sill":0, "head":8, "panels":1}],
  "rooms": [{"name":"Room name", "level":"L1", "polygon":[[0,0],[10,0],[10,10]],
             "ha_area":"optional HA area id"}],
  "stairs": [{"level":"L1", "from":[1,1], "to":[10,1], "width":4,
              "risers":17, "rise_to":11}],
  "roof": {"main":{"kind":"gable", "ridge_axis":"y", "x0":0, "x1":30,
                   "y0":0, "y1":20, "pitch":11, "plate":10, "overhang":1},
           "extensions":[{"kind":"shed_continuation", "side":"x1", "to_x":37,
                          "pitch":3, "overhang":1}]},
  "porch": {"polygon":[[30,0],[37,0],[37,20],[30,20]], "floor":0.5,
            "columns":[{"at":[36,1], "size":0.667}]},
  "fixtures": [{"kind":"counter", "level":"L1", "rect":[1,1,5,3], "height":3}],
  "lights": [{"room":"Room name", "kind":"recessed", "at":[5,5], "level":"L1"}]
}
The numbers above explain the schema; they are not evidence about this house.
Include readable walls, openings, rooms, stairs, roof, porch, fixtures, and
lights from electrical sheets. IDs must match within each building. Opening
at is distance along its wall to its centre; sill/head are heights above the
referenced level, not world elevations. Gable openings instead use
{"gable":"front" or "rear", "x":15, "kind":"window", "width":3, "sill":2, "head":8}.
An opening references exactly one wall or gable. Rooms need level IDs and
polygons with at least three points. Use provided HA area names for unnamed
rooms when suitable; otherwise leave names blank for descriptive labels.
""" + _RULES

FINISHES_PROMPT = """Read the household photos and return only
{"materials": {"role": {"id":"allowed_kit_asset", "color":"#rrggbb"}}}.
Use the material roles and allowed asset IDs supplied in the user prompt.
Match visible finishes and colours to these assets; use a role's kit default
when the photographs do not establish a finish. Do not change geometry.
""" + _RULES

SITE_PROMPT = """Read the plot plan and return {"site": {...}} using:
{
  "site": {
    "lot": [[0,0],[100,0],[100,100],[0,100]],
    "hardscape": [{"kind":"patio", "polygon":[[0,0],[10,0],[10,10]], "material":"paving"}],
    "pool": {"polygon":[[0,0],[10,0],[10,20],[0,20]], "depth":5, "coping":1},
    "fire_pit": {"at":[20,20], "radius":3},
    "building_positions": {"building_id":[0,0]}
  }
}
The example numbers are schema examples only. Use the supplied building IDs
for building_positions, which locates each building's local origin on the lot.
Keep building-local geometry unchanged. Omit features absent or unreadable in
the plot plan. Do not invent planting or furnishings; composition adds those.
""" + _RULES

_LOCK = threading.Lock()


def _save(path, value):
    """Expose complete JSON only, so a stopped stage can be resumed safely."""
    temporary = path.with_name(f'.{path.name}-{uuid.uuid4().hex}.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as file:
            json.dump(value, file, ensure_ascii=False, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _images(drawings, photos, site):
    if not isinstance(drawings, list) or not isinstance(photos, list):
        raise ValueError('Drawings and photos must be lists.')

    def pages(source):
        if not isinstance(source, dict) or not isinstance(source.get('id'), str):
            raise ValueError('A drawing or plot plan needs a source id.')
        return source_images(source['id'], source.get('pages'))

    def source_images(source_id, selected=None):
        if not isinstance(source_id, str) or not source_id:
            raise ValueError('A source id is required.')
        try:
            return twin_store.source_images(source_id, selected)
        except KeyError as exc:
            raise ValueError(f'Unknown twin source: {source_id}') from exc

    images = {
        'building': [image for source in drawings for image in pages(source)],
        'finishes': [image for source_id in photos for image in source_images(source_id)],
        'site': pages(site) if site is not None else [],
    }
    for stage, selected in images.items():
        if len(selected) > 16:
            raise ValueError(f'The {stage} stage accepts at most 16 pages or photos.')
    return images


def _area_names():
    try:
        return list(dict.fromkeys(row['name'].strip() for row in ha_api.get_area_registry()
                                 if isinstance(row, dict) and isinstance(row.get('name'), str)
                                 and row['name'].strip()))
    except Exception:
        return []


def _stage(stage, root, key, prompt, user, images, run, settings):
    target = root / f'{stage}.json'
    if target.is_file():
        return json.loads(target.read_text(encoding='utf-8'))
    usage = []
    twin_cost.require_clear()
    try:
        answer = model_pools.call_pool_json(
            'twin', key, prompt, user, images=images, strict_json=True,
            max_models=1, max_output_tokens=16384 if stage == 'building' else 8192,
            usage=usage, settings=settings)
    except Exception as exc:
        answer = {'error': str(exc)}
    finally:
        twin_cost.record(stage, usage, run)
    field = {'building': 'buildings', 'finishes': 'materials', 'site': 'site'}[stage]
    expected = list if stage == 'building' else dict
    if not isinstance(answer, dict):
        return {'error': f'{stage} returned an invalid JSON fragment.'}
    if 'error' in answer:
        return answer
    if not isinstance(answer.get(field), expected):
        return {'error': f'{stage} returned no valid {field} fragment.'}
    _save(target, answer)
    return answer


def _materials(answer, kit, notes):
    defaults = {role: {'id': value['asset'], 'color': value['color']}
                for role, value in kit['materials'].items()}
    if 'error' in answer:
        notes.append(f"finishes failed; using kit defaults: {answer['error']}")
        return defaults
    allowed = {value['asset'] for value in kit['materials'].values()}
    for role, value in answer['materials'].items():
        if role not in defaults:
            notes.append(f'Ignored finishes role {role}: not in the kit.')
            continue
        asset_id = value.get('id') if isinstance(value, dict) else value
        if not isinstance(value, dict) or not isinstance(asset_id, str) or asset_id not in allowed:
            notes.append(f'Replaced finishes asset {asset_id} for {role} with its kit default.')
            continue
        color = value.get('color')
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            notes.append(f'Used kit colour for finishes role {role}: invalid colour {color}.')
            color = defaults[role]['color']
        defaults[role] = {'id': asset_id, 'color': color}
    return defaults


def draft(drawings: list[dict], photos: list[str], site: dict | None,
          kit_id: str = 'modern_farmhouse', run: str | None = None
          ) -> tuple[dict | None, list[str], str | None]:
    notes = []
    if not _LOCK.acquire(blocking=False):
        return None, notes, 'a draft is already running'
    try:
        base = twin_store.current_id()
        if run is None:
            run = uuid.uuid4().hex
        if not isinstance(run, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run):
            raise ValueError('Invalid twin draft run id.')
        settings = storage.get_settings()
        _, key = model_pools.credentials('twin', settings)
        if not key:
            return None, notes, 'No model key is configured for twin drafting.'
        images = _images(drawings, photos, site)
        kit = twin_library.kit(kit_id)
        root = Path(twin_store.DATA_DIR) / 'runs' / run
        root.mkdir(parents=True, exist_ok=True)
        metadata_path = root / 'run.json'
        inputs = {'drawings': drawings, 'photos': photos, 'site': site, 'kit': kit_id}
        if metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            if metadata['inputs'] != inputs:
                raise ValueError('A resumed draft must use the same sources, pages and kit.')
        else:
            metadata = {'base': base, 'inputs': inputs, 'area_names': _area_names()}
            _save(metadata_path, metadata)

        building = _stage('building', root, key, BUILDING_PROMPT,
                          'Read these drawing pages. HA area names: '
                          + json.dumps(metadata['area_names'], ensure_ascii=False),
                          images['building'], run, settings)
        if 'error' in building:
            return None, notes, f"building failed: {building['error']}"
        finishes = _stage('finishes', root, key, FINISHES_PROMPT,
                          'Match these photos using the kit material roles and defaults: '
                          + json.dumps(kit['materials']) + '\nAllowed asset IDs: '
                          + json.dumps(sorted({v['asset'] for v in kit['materials'].values()})),
                          images['finishes'], run, settings)
        site_answer = _stage('site', root, key, SITE_PROMPT,
                             'Read these plot plan pages. Buildings (local geometry): '
                             + json.dumps(building['buildings']), images['site'], run, settings)
        site_data = {}
        if 'error' in site_answer:
            notes.append(f"site failed; using an empty site: {site_answer['error']}")
        else:
            site_data.update(site_answer['site'])
        plan, normalized_notes = twin_plan.normalize({
            'units': 'ft', 'buildings': building['buildings'],
            'materials': _materials(finishes, kit, notes), 'site': site_data})
        notes.extend(normalized_notes)
        names = iter(metadata['area_names'])
        room_number = 0
        positions = site_data.get('building_positions', {})
        for building in plan['buildings']:
            position = positions.get(building.get('id')) if isinstance(positions, dict) else None
            if position is not None:
                if (isinstance(position, list) and len(position) == 2
                        and all(type(v) in (int, float) and math.isfinite(v) for v in position)):
                    building['position'] = deepcopy(position)
                else:
                    notes.append(f"Ignored invalid site position for {building.get('id')}.")
            for room in building['rooms']:
                room_number += 1
                if not isinstance(room.get('name'), str) or not room['name'].strip():
                    room['name'] = next(names, f'Room {room_number}')
        plan, composed_notes = twin_compose.compose(plan, kit, seed=1)
        notes.extend(composed_notes)
        cost = math.fsum(entry['usd'] for entry in twin_cost.entries() if entry.get('run') == run)
        round_id = twin_store.push_round(plan, 'draft', '\n'.join(notes), cost=cost,
                                         run=run, base=metadata['base'])
        return {'round': round_id, 'plan': plan, 'cost': cost, 'run': run}, notes, None
    except twin_cost.CheckpointReached as exc:
        exc.run = run
        raise
    except Exception as exc:
        return None, notes, str(exc)
    finally:
        _LOCK.release()
