"""Pure place records, validation and migration; no storage dependencies."""

import math
import re

from services import twin_register


KINDS = {
    'main_house': 'Main house', 'garage': 'Garage', 'adu': 'ADU or guest house',
    'pool_house': 'Pool house', 'shed': 'Shed', 'greenhouse': 'Greenhouse',
    'barn': 'Barn', 'studio': 'Studio or office', 'workshop': 'Workshop', 'other': 'Other',
}
SHELL_DEFAULT = {'storeys': 1, 'wall_height': 8, 'roof': 'gable', 'pitch': 6, 'door_side': 'front'}
KIND_SHELL = {
    'main_house': {'storeys': 2, 'wall_height': 9}, 'garage': {'wall_height': 9},
    'adu': {'wall_height': 9}, 'pool_house': {'wall_height': 9},
    'greenhouse': {'wall_height': 7, 'pitch': 8}, 'barn': {'wall_height': 12, 'pitch': 8},
    'studio': {'wall_height': 9}, 'workshop': {'wall_height': 10},
}
BUILDING_ROLES = ('floor', 'roof', 'elevation', 'other', 'skip')
LOT_ROLES = ('plot', 'survey', 'landscape', 'other', 'skip')
LOT = 'lot'


def shell_for(kind) -> dict:
    return {**SHELL_DEFAULT, **KIND_SHELL.get(kind, {})}


def _bounded(value, low, high):
    return (type(value) in (int, float) and low <= value <= high
            and math.isfinite(value))


def check_shell(card) -> dict:
    if not isinstance(card, dict):
        raise ValueError('A shell needs its dimensions and roof shape.')
    result = {**SHELL_DEFAULT, **card}
    if type(result['storeys']) is not int or not 1 <= result['storeys'] <= 4:
        raise ValueError('Choose one to four storeys.')
    if not _bounded(result['wall_height'], 6, 20):
        raise ValueError('Wall height must be between 6 and 20 feet.')
    if result['roof'] not in ('gable', 'hip', 'shed', 'flat'):
        raise ValueError('Choose a gable, hip, shed or flat roof.')
    if not _bounded(result['pitch'], 0, 24):
        raise ValueError('Roof pitch must be between 0 and 24.')
    if result['roof'] == 'flat':
        result['pitch'] = 0
    if result['door_side'] not in ('front', 'back', 'left', 'right'):
        raise ValueError('Choose the front, back, left or right side for the door.')
    return result


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a, b, p):
    return (min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1]))


def _intersects(a, b, c, d):
    ab_c, ab_d, cd_a, cd_b = _cross(a, b, c), _cross(a, b, d), _cross(c, d, a), _cross(c, d, b)
    return ((ab_c * ab_d < 0 and cd_a * cd_b < 0)
            or (ab_c == 0 and _on_segment(a, b, c))
            or (ab_d == 0 and _on_segment(a, b, d))
            or (cd_a == 0 and _on_segment(c, d, a))
            or (cd_b == 0 and _on_segment(c, d, b)))


def check_footprint(points) -> list:
    if not isinstance(points, (list, tuple)) or not 3 <= len(points) <= 64:
        raise ValueError('A footprint needs between 3 and 64 points.')
    if any(not isinstance(p, (list, tuple)) or len(p) != 2
           or any(not _bounded(v, -2000, 2000) for v in p) for p in points):
        raise ValueError('Footprint points must be finite and within 2000 feet of the origin.')
    result = [list(p) for p in points]
    count = len(result)
    for i, a in enumerate(result):
        b, previous = result[(i + 1) % count], result[i - 1]
        if a == b:
            raise ValueError('A footprint needs distinct neighbouring points.')
        # Adjacent edges may meet, but must not double back over each other.
        if _cross(previous, a, b) == 0 and (
                (previous[0] - a[0]) * (b[0] - a[0])
                + (previous[1] - a[1]) * (b[1] - a[1])) > 0:
            raise ValueError('A footprint cannot cross itself.')
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue
            if _intersects(a, b, result[j], result[(j + 1) % count]):
                raise ValueError('A footprint cannot cross itself.')
    area = abs(sum(p[0] * result[(i + 1) % count][1]
                   - p[1] * result[(i + 1) % count][0] for i, p in enumerate(result))) / 2
    if area < 4:
        raise ValueError('A footprint must cover at least 4 square feet.')
    return result


def new_id(name, taken) -> str:
    stem = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:40].rstrip('-') or 'building'
    candidate, number = stem, 2
    while candidate == LOT or candidate in taken:
        suffix = f'-{number}'
        candidate = stem[:40 - len(suffix)].rstrip('-') + suffix
        number += 1
    return candidate


def empty_place() -> dict:
    return {'buildings': [], 'lot': {'placement': None, 'read': None}, 'photo_tags': {}}


def migrate(row: dict, plan: dict | None) -> dict:
    result = empty_place()
    planned = {b['id']: b for b in (plan or {}).get('buildings', [])}
    ids = []
    for page in row.get('page_roles', []):
        if page.get('role') != 'plot':
            bid = page.get('building', 'house')
            if bid != LOT and bid not in ids:
                ids.append(bid)
    ids.extend(bid for bid in planned if bid != LOT and bid not in ids)
    if 'house' not in ids and any(
            s['kind'] == 'drawing'
            and not any(p['source'] == s['id'] for p in row.get('page_roles', []))
            for s in row.get('sources', [])):
        ids.append('house')
    for bid in ids:
        kind = {'house': 'main_house', 'pool_house': 'pool_house'}.get(bid, 'other')
        name = planned.get(bid, {}).get('name') or (KINDS[kind] if kind != 'other' else bid)
        result['buildings'].append({
            'id': bid, 'name': name, 'kind': kind, 'footprint': None, 'footprint_from': None,
            'shell': shell_for(kind), 'shell_from': 'default',
        })
    result['photo_tags'] = {s['id']: [*ids, LOT] for s in row.get('sources', []) if s['kind'] == 'photo'}
    return result


def to_master(crop, uv) -> list:
    x0, y0, x1, y1 = crop['box']
    width, height = crop['master']
    return [(x0 + uv[0] * (x1 - x0)) * width,
            (y0 + uv[1] * (y1 - y0)) * height]


def plot_registration(crop, fragment, edge=None) -> dict:
    """Place the street on the x axis, with the lot behind it at positive y."""
    dim = fragment['scale']
    scale = twin_register.from_dimension(to_master(crop, dim['a']), to_master(crop, dim['b']), dim['feet'])
    lot = [to_master(crop, p) for p in fragment['lot']]
    explicit_edge = edge is not None
    if edge is None:
        edge = fragment.get('street_edge')
    if edge is None:
        i = max(range(len(lot)), key=lambda i: math.dist(lot[i], lot[(i + 1) % len(lot)]))
        edge = [i, (i + 1) % len(lot)]
    if explicit_edge and (not isinstance(edge, list) or len(edge) != 2
            or any(type(i) is not int or not 0 <= i < len(lot) for i in edge)
            or (edge[1] - edge[0]) % len(lot) not in (1, len(lot) - 1)):
        raise ValueError('Choose two neighbouring lot corners for the street edge.')
    a, b = (lot[i] for i in edge)
    reg = twin_register.from_two_points(a, b, [0, 0], [math.dist(a, b) * scale, 0])
    edges = list(zip(lot, lot[1:] + lot[:1]))
    area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in edges)
    centre = ([sum((a[i] + b[i]) * (a[0] * b[1] - b[0] * a[1])
                   for a, b in edges) / (3 * area2) for i in (0, 1)]
              if abs(area2) >= 1e-9 else [sum(p[i] for p in lot) / len(lot) for i in (0, 1)])
    if twin_register.apply(reg, centre)[1] < 0:
        reg = twin_register.from_two_points(b, a, [0, 0], [math.dist(a, b) * scale, 0])
    return reg


def plot_suggestions(fragment, crop, reg) -> list[dict]:
    lot = [twin_register.apply(reg, to_master(crop, p)) for p in fragment['lot']]
    bounds = [[min(p[i] for p in lot), max(p[i] for p in lot)] for i in (0, 1)]
    suggestions = []
    for number, building in enumerate(fragment.get('buildings', []), 1):
        pixels = [to_master(crop, p) for p in building['outline']]
        world = [twin_register.apply(reg, p) for p in pixels]
        bands = [(sum(p[i] for p in world) / len(world) - lo) / (hi - lo) if hi > lo else .5
                 for i, (lo, hi) in enumerate(bounds)]
        horizontal = 'left' if bands[0] < 1/3 else 'right' if bands[0] > 2/3 else ''
        depth = 'front' if bands[1] < 1/3 else 'back' if bands[1] > 2/3 else ''
        where = ' '.join(filter(None, (depth, horizontal))) or 'middle'
        suggestions.append({'id': f'plot-{number}', 'outline': world, 'outline_px': pixels,
                            'size_ft': [max(p[i] for p in world) - min(p[i] for p in world) for i in (0, 1)],
                            'where': 'at the ' + where, 'name': building['name'],
                            'state': 'open', 'building': None})
    return suggestions


def sheet_matrix(reg, crop) -> list:
    """SVG affine matrix from full-page uv, independent of the read's crop."""
    origin = twin_register.apply(reg, [0, 0])
    x = twin_register.apply(reg, [crop['master'][0], 0])
    y = twin_register.apply(reg, [0, crop['master'][1]])
    return [x[0] - origin[0], x[1] - origin[1], y[0] - origin[0], y[1] - origin[1], *origin]
