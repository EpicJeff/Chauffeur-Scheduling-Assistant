"""Explicit porch-to-roof post transfer; the ordinary house history owns undo."""
from copy import deepcopy
import math

from services import twin_model, twin_model_roofs
from services.twin_model_supports import frame_point, is_supported


def _covers_column(roof, sections, at):
    """Match twin_roof.roofBounds in roof-local space, with 0.05 ft tolerance."""
    x, y = frame_point(roof, at, inverse=True)
    for section in sections:
        x0, y0, x1, y1 = section['rect']
        overhang = section.get('overhang', 0)
        edges = section.get('edges', [])
        edge = lambda i: edges[i].get('overhang_ft', overhang) if i < len(edges) else overhang
        bounds = (x0-edge(3), y0-edge(0), x1+edge(1), y1+edge(2))
        dx = max(bounds[0]-x, 0, x-bounds[2])
        dy = max(bounds[1]-y, 0, y-bounds[3])
        if math.hypot(dx, dy) <= .05 + 1e-8:
            return True
    return False


def post_roof_reason(building, porch, roof, *, states_only=False):
    """Single server eligibility rule; parity pinned to postRoofReason by cases."""
    if porch is not None and porch.get('state') in ('ghost', 'proposal'):
        return 'Choose a settled porch; ghost and proposal porches cannot move posts.'
    if roof is not None and roof.get('state') in ('ghost', 'proposal'):
        return 'Choose a settled roof; ghost and proposal roofs cannot receive posts.'
    if states_only:
        return None
    if porch is None or not porch.get('columns'):
        return 'This porch has no columns to move.'
    area = [frame_point(roof, p) for p in roof['area']] if roof else []
    level = porch.get('level') or next((r['level'] for r in building['rooms'] if r['id'] == porch['id']), None)
    if roof is None or roof.get('level') != level or twin_model._overlap(porch['polygon'], area) <= 1e-8:
        return 'No roof overlaps this porch on its floor.'
    if is_supported(roof):
        return 'This roof already has supports.'
    sections = twin_model_roofs.to_sections(roof)
    if not sections or any(s['kind'] != 'shed' for s in sections):
        return 'Choose a shed roof; this walled roof is not a shed.'
    columns = porch['columns']; size = columns[0]['size']
    if len(columns) > 40 or not .05 <= size <= 3 or any(abs(c['size']-size) > 1e-8 for c in columns):
        return 'The roof needs at most 40 columns of the same size, from 0.05 to 3 feet.'
    if any(not _covers_column(roof, sections, c['at']) for c in columns):
        return 'A column centre is outside the roof perimeter (including overhang; tolerance 0.05 ft).'
    return None


def validate_move_posts(model, op, *, states_only=False):
    from services.twin_model_ops import Refused
    building = next((b for b in model['buildings'] if b['id'] == op.get('building')), None)
    if building is None:
        raise Refused('That building is missing.')
    porch = next((p for p in building.get('porches_detail', []) if p['id'] == op.get('porch')), None)
    roof = next((r for r in building.get('roofs', []) if r['id'] == op.get('roof')), None)
    if reason := post_roof_reason(building, porch, roof, states_only=states_only):
        raise Refused(reason)
    return porch, roof


def move_posts_to_roof(model, op, actor='person'):
    from services.twin_model_ops import _person
    porch, roof = validate_move_posts(model, op)
    columns = porch['columns']; size = columns[0]['size']
    roof['support'] = dict(kind='post', count=len(columns), size_ft=size,
                           at={str(i): deepcopy(c['at']) for i, c in enumerate(columns)})
    material = porch.get('materials', {}).get('column')
    if material:
        roof.setdefault('materials', {})['support'] = deepcopy(material)
    if 'materials' in roof and not roof['materials']:
        roof.pop('materials')
    porch['columns'] = []
    if actor == 'person':
        _person(roof)
        _person(porch)
    return 'Moved the posts to the roof. The porch floor stays; the roof stops shaping walls and gables under it.'
