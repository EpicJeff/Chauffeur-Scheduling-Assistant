"""Validation for authored yard edits; polygon topology is owned by terrain."""
import math
import re
from services import twin_terrain as terrain


KINDS = ('beds', 'hardscape', 'edges', 'pool', 'fire_pit', 'fence', 'yard_rooms')
MATERIALS = ('mulch', 'patio_concrete', 'paving', 'lawn', 'base', 'fence')
FIRE_FIELDS = {'fuel', 'body', 'top', 'height_in', 'glass', 'entity'}
# Library material slots per feature part (user, 2026-11-13: "Why doesn't everything just have
# a material slot"). A missing part is the feature's own default look.
SLOTS = {'beds': ('fill',), 'hardscape': ('surface', 'edging'), 'fire_pit': ('body', 'top'),
         'fence': ('boards', 'posts', 'rails'), 'pool': ('coping', 'interior'), 'edges': ('strip',),
         'spa': ('coping', 'interior', 'wall')}


def _segments(poly):
    return zip(poly, poly[1:] + poly[:1])


def _edge_distance(p, a, b):
    length = sum((b[i]-a[i])**2 for i in (0, 1))
    t = max(0, min(1, sum((p[i]-a[i])*(b[i]-a[i]) for i in (0, 1))/length)) if length else 0
    return math.dist(p, [a[i]+t*(b[i]-a[i]) for i in (0, 1)])


def _contained(outline, poly):
    # Split at every boundary crossing, including collinear boundary vertices.
    # Vertex-only checks miss a shape bridging a notch in a concave pool.
    for a, b in _segments(poly):
        ts = [0, 1]
        length = sum((b[i]-a[i])**2 for i in (0, 1))
        for c, d in _segments(outline):
            den = terrain.cross([0, 0], [b[i]-a[i] for i in (0, 1)], [d[i]-c[i] for i in (0, 1)])
            if abs(den) > 1e-10 and terrain.intersects(a, b, c, d):
                ts.append(terrain.cross(a, c, d)/den)
            for p in (c, d):
                if _edge_distance(p, a, b) < 1e-8:
                    ts.append(sum((p[i]-a[i])*(b[i]-a[i]) for i in (0, 1))/length)
        ts = sorted(ts)
        if any(not terrain.inside(outline, [a[i]+t*(b[i]-a[i]) for i in (0, 1)])
               for t in [*ts, *((x+y)/2 for x, y in zip(ts, ts[1:]))]):
            return False
    return True


def pool_feature(pool, value):
    """Validate one drawn feature and return its canonical defaults, in lot feet."""
    from copy import deepcopy
    if not isinstance(value, dict) or value.get('kind') not in ('ledge', 'steps', 'spa'):
        raise ValueError('Choose a tanning ledge, steps or spa.')
    piece = deepcopy(value)
    kind = piece['kind']
    allowed = {'id', 'kind', 'polygon'} | {'ledge': {'depth_in'}, 'steps': {'treads', 'entry_edge'},
        'spa': {'mode', 'raise_in', 'depth_in', 'spillover', 'materials'}}[kind]
    if set(piece) - allowed or not isinstance(piece.get('id'), str) or not 1 <= len(piece['id']) <= 100:
        raise ValueError('Use a pool feature id and supported properties.')
    validate('beds', {'polygon': piece.get('polygon')})
    poly, outline = piece['polygon'], pool['polygon']
    if kind != 'spa' and not _contained(outline, poly):
        raise ValueError('Draw the ledge or steps inside the pool.')
    if kind == 'spa':
        touching = (any(terrain.inside(outline, p) for p in poly) or any(terrain.inside(poly, p) for p in outline)
                    or any(terrain.intersects(a, b, c, d) for a, b in _segments(poly) for c, d in _segments(outline)))
        distance = min(_edge_distance(p, a, b) for points, edges in ((poly, outline), (outline, poly))
                       for p in points for a, b in _segments(edges))
        if not touching and distance > 2 + 1e-8:
            raise ValueError('Draw the spa within 2 feet of the pool.')
        piece.setdefault('mode', 'raised')
        piece.setdefault('spillover', True)
        if piece['mode'] not in ('raised', 'flush') or type(piece['spillover']) is not bool:
            raise ValueError('Choose raised or flush and a boolean spillover.')
        if 'materials' in piece:
            piece['materials'] = material_slots('spa', piece['materials'])
            if not piece['materials']:
                piece.pop('materials')
    ranges = {'ledge': [('depth_in', 10, 6, 18)], 'steps': [('treads', 3, 1, 6)],
              'spa': [('raise_in', 12, 6, 24), ('depth_in', 36, 24, 48)]}[kind]
    for field, default, low, high in ranges:
        piece.setdefault(field, default)
        if not terrain.number(piece[field]) or not low <= piece[field] <= high or field == 'treads' and type(piece[field]) is not int:
            raise ValueError(f'Choose {field} from {low} to {high}.')
    if kind == 'steps':
        piece.setdefault('entry_edge', min(range(len(poly)), key=lambda i:
            min(_edge_distance([(poly[i][j]+poly[(i+1) % len(poly)][j])/2 for j in (0, 1)], a, b)
                for a, b in _segments(outline))))
        if type(piece['entry_edge']) is not int or not 0 <= piece['entry_edge'] < len(poly):
            raise ValueError('Choose an entry edge of the step polygon.')
    return piece


def pool_features(pool):
    values = pool.get('features', [])
    if not isinstance(values, list) or len(values) > 12:
        raise ValueError('A pool supports at most 12 drawn features.')
    result = [pool_feature(pool, p) for p in values]
    if len({p['id'] for p in result}) != len(result):
        raise ValueError('Pool feature ids must be unique.')
    return result


def material_slots(name, value, previous=None):
    """Merge a partial {part: slot or null}; null returns that part to the feature default."""
    from services.twin_library import normalize_material_slot
    parts = SLOTS.get(name)
    if not parts:
        raise ValueError('This yard shape has no material slots.')
    if not isinstance(value, dict) or set(value) - set(parts):
        raise ValueError(f"Choose material slots from: {', '.join(parts)}.")
    merged = dict(previous or {})
    for part, slot in value.items():
        slot = normalize_material_slot(slot)
        if slot is None:
            merged.pop(part, None)
        else:
            merged[part] = slot
    return merged


def fire_properties(piece):
    """Validate optional finishes without materializing defaults on legacy pits."""
    for field, choices, default in [('fuel', ('wood', 'gas'), 'wood'),
            ('body', ('stone', 'brick', 'concrete'), 'stone'),
            ('top', ('none', 'granite', 'concrete'), 'none'),
            ('glass', ('amber', 'blue', 'clear'), 'amber')]:
        if piece.get(field, default) not in choices:
            raise ValueError(f'Choose a supported fire pit {field}.')
    if 'glass' in piece and piece.get('fuel', 'wood') != 'gas':
        raise ValueError('Fire glass belongs in a gas pit.')
    if 'height_in' in piece and (not terrain.number(piece['height_in']) or not 6 <= piece['height_in'] <= 30):
        raise ValueError('Choose a fire pit height from 6 to 30 inches.')
    entity = piece.get('entity')
    if entity is not None and (not isinstance(entity, str) or len(entity) > 255 or not re.fullmatch(r'(switch|light|input_boolean|fan)\.[a-z0-9_]+', entity)):
        raise ValueError('Choose a switch, light, input boolean or fan entity.')
    gas = piece.get('fuel') == 'gas'
    return {'fuel': piece.get('fuel', 'wood'), 'body': piece.get('body', 'stone'),
            'top': piece.get('top', 'granite' if gas else 'none'),
            'height_in': piece.get('height_in', 18 if gas else 16.8),
            **({'glass': piece.get('glass', 'amber')} if gas else {})}


PATH_PRESETS = {
    'sidewalk': {'width': 4, 'material': 'patio_concrete', 'corner': 'mitred'},
    'paver': {'width': 3, 'material': 'paving', 'corner': 'rounded'},
    'driveway': {'width': 10, 'material': 'patio_concrete', 'corner': 'mitred'},
}


def pieces(value):
    """Read legacy singleton site fields and authored collections uniformly."""
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


def yard_device_point(site, device):
    """Resolve a floor-style bounding-box host, rejecting points outside concave rooms."""
    host = device.get('host')
    if not isinstance(host, dict) or set(host) != {'yard_room', 'u', 'v'}:
        raise ValueError('Pick the ground inside a yard room.')
    room = next((r for r in site.get('yard_rooms', []) if r['id'] == host['yard_room']), None)
    if room is None or any(not terrain.number(host[k]) or not 0 <= host[k] <= 1 for k in ('u', 'v')):
        raise ValueError('Pick the ground inside a yard room.')
    offset = device.get('offset', 0)
    if not terrain.number(offset) or not 0 <= offset <= 100:
        raise ValueError('Choose a height above ground from 0 to 100 feet.')
    polygon = room['polygon']
    low = [min(p[i] for p in polygon) for i in (0, 1)]
    high = [max(p[i] for p in polygon) for i in (0, 1)]
    point = [low[i] + (high[i]-low[i])*host[k] for i, k in enumerate(('u', 'v'))]
    if not terrain.inside(polygon, point):
        raise ValueError('Pick the ground inside the yard room outline.')
    return point


def room_from_feature(name, piece, feature=None):
    """Copy a ground feature's footprint without changing its physical geometry."""
    if name not in ('pool', 'hardscape', 'beds', 'fire_pit'):
        raise ValueError('Choose a pool, patio, planting bed or fire pit.')
    if feature is not None:
        spa = next((p for p in piece.get('features', []) if p['id'] == feature and p['kind'] == 'spa'), None) if name == 'pool' else None
        if spa is None:
            raise ValueError('Choose a spa to make a room.')
        from copy import deepcopy
        return {'name': 'Spa', 'polygon': deepcopy(spa['polygon']),
                'feature': {'list': 'pool', 'id': piece['id'], 'feature': feature}}
    if name == 'fire_pit' and piece.get('shape', 'round') == 'round':
        x, y = piece['at']
        radius = piece.get('radius', 2) + 1.5
        polygon = [[x + radius*math.cos(i*math.pi/16), y + radius*math.sin(i*math.pi/16)] for i in range(32)]
    else:
        polygon = piece.get('polygon')
    if not polygon:
        raise ValueError('Choose a feature with a closed outline.')
    from copy import deepcopy
    return {'name': (piece.get('name') or {'pool': 'Pool', 'hardscape': 'Patio', 'beds': 'Planting bed', 'fire_pit': 'Fire pit'}[name]).strip()[:40],
            'polygon': deepcopy(polygon), **({'feature': {'list': name, 'id': piece['id']}} if piece.get('id') else {})}


def create(name, values, lot):
    if name not in KINDS:
        raise ValueError('Choose a ground feature.')
    path = values.get('kind') == 'path'
    if path and name != 'hardscape' or values.get('kind') not in (None, 'path'):
        raise ValueError('Paths belong in hardscape.')
    defaults = {'material': 'mulch' if name == 'beds' else 'lawn' if name == 'edges' else 'patio_concrete'}
    allowed = {'polygon', 'material'}
    if name == 'yard_rooms':
        defaults = {'name': 'Yard room'}
        allowed = {'polygon', 'name', 'ha_area', 'feature'}
    if name == 'pool':
        defaults.update(depth=5, coping=1, material='paving')
        allowed |= {'depth', 'coping', 'features'}
    if name == 'fire_pit':
        shape = values.get('shape', 'round')
        if shape not in ('round', 'square', 'rect', 'outline'):
            raise ValueError('Choose Round, Square, Rectangle or Drawn outline.')
        defaults = {'shape': shape, 'fuel': 'wood'}
        if shape == 'round':
            defaults['radius'] = 2
            allowed = {'shape', 'at', 'radius'}
        elif shape in ('square', 'rect') and 'polygon' not in values:
            at = values.get('at')
            width = values.get('side', 4) if shape == 'square' else values.get('width', 4)
            depth = width if shape == 'square' else values.get('depth', 6)
            if (not isinstance(at, list) or len(at) != 2 or not all(terrain.number(v) for v in at)
                    or any(not terrain.number(v) or not .1 <= v <= 200 for v in (width, depth))):
                raise ValueError('Choose a ground point and pit dimensions from 0.1 to 200 feet.')
            allowed = ({'shape', 'at', 'side'} if shape == 'square' else {'shape', 'at', 'width', 'depth'}) | FIRE_FIELDS
            if set(values) - allowed:
                raise ValueError('Choose supported fire pit properties.')
            x, y = at
            values = {**{k: v for k, v in values.items() if k in FIRE_FIELDS}, 'shape': shape, 'polygon': [[x-width/2, y-depth/2], [x+width/2, y-depth/2], [x+width/2, y+depth/2], [x-width/2, y+depth/2]]}
            allowed = {'shape', 'polygon'}
        else:
            allowed = {'shape', 'polygon'}
        allowed |= FIRE_FIELDS
    if name == 'fence':
        defaults = {'height': 6}
        allowed = {'polyline', 'height', 'style'}
    if path:
        preset = values.get('preset')
        if preset is not None and (not isinstance(preset, str) or preset not in PATH_PRESETS):
            raise ValueError('Choose Sidewalk, Paver path or Driveway.')
        defaults.update(width=3, corner='mitred', smooth=False, edging='none')
        defaults.update(PATH_PRESETS.get(preset, {}))
        allowed = {'kind', 'points', 'width', 'corner', 'radius', 'smooth', 'material', 'edging', 'preset'}
    if set(values) - allowed:
        raise ValueError('Choose supported drawing properties.')
    piece = {**defaults, **values}
    if 'material' in piece and piece['material'] not in MATERIALS:
        raise ValueError('Choose an existing kit material role.')
    validate(name, piece)
    key = 'at' if name == 'fire_pit' and piece['shape'] == 'round' else 'polyline' if name == 'fence' else 'points' if path else 'polygon'
    words = update(name, piece, {key: piece[key]}, lot)
    return piece, words.replace('Changed', 'Added', 1)


def validate(name, piece, *, legacy_height=False):
    if name == 'yard_rooms':
        feature = piece.get('feature')
        if feature is not None and (not isinstance(feature, dict) or set(feature) not in ({'list', 'id'}, {'list', 'id', 'feature'})
                or feature['list'] not in ('pool', 'hardscape', 'beds', 'fire_pit')
                or not isinstance(feature['id'], str) or not feature['id']
                or 'feature' in feature and (feature['list'] != 'pool' or not isinstance(feature['feature'], str) or not feature['feature'])):
            raise ValueError('Choose a yard feature reference.')
        if not isinstance(piece.get('name'), str) or not 1 <= len(piece['name'].strip()) <= 40:
            raise ValueError('Use a room name of 1 to 40 characters.')
        area = piece.get('ha_area')
        if area is not None and (not isinstance(area, str) or len(area) > 255):
            raise ValueError('Choose a Home Assistant area.')
        if not isinstance(piece.get('polygon'), list):
            raise ValueError('Draw a yard room outline.')
    key = next((k for k in ('polygon', 'points', 'polyline') if k in piece), None)
    path = name == 'hardscape' and piece.get('kind') == 'path'
    if path and (key != 'points' or 'polygon' in piece or 'polyline' in piece):
        raise ValueError('Use a centre line for a path.')
    round_pit = name == 'fire_pit' and piece.get('shape', 'round') == 'round'
    if name == 'fire_pit':
        fire_properties(piece)
        if piece.get('shape', 'round') not in ('round', 'square', 'rect', 'outline'):
            raise ValueError('Choose a fire pit shape.')
        if (round_pit and key is not None or not round_pit and (key != 'polygon' or 'at' in piece or 'radius' in piece)):
            raise ValueError('Round pits use a centre and radius; other pits use an outline.')
    closed = not path and (name in ('beds', 'hardscape', 'pool', 'yard_rooms') or key == 'polygon')
    if round_pit:
        points = [piece.get('at')]
    else:
        points = piece.get(key) if key else None
    if (not isinstance(points, list) or not (1 if round_pit else 3 if closed else 2) <= len(points) <= 200
            or any(not isinstance(p, (list, tuple)) or len(p) != 2 or not all(terrain.number(v) for v in p) for p in points)):
        raise ValueError('Use finite lot points: 3 to 200 corners for polygons, 2 to 200 for lines.')
    if closed:
        error = terrain.pad_error({'polygon': points, 'height': 0})
        if error:
            raise ValueError(error)
    elif any(math.dist(a, b) < .01 for a, b in zip(points, points[1:])):
        raise ValueError('Keep line points at least 0.01 feet apart.')
    sizes = [max(p[i] for p in points) - min(p[i] for p in points) for i in (0, 1)]
    if max(sizes) > 2000 or closed and min(sizes) < .01:
        raise ValueError('Keep shapes between 0.01 and 2000 feet across.')
    if any(abs(v) > 10000 for p in points for v in p):
        raise ValueError('Keep lot coordinates within 10000 feet.')
    if path:
        for field, default, low, high in [('width', 3, 1, 30), ('radius', piece.get('width', 3), .1, 200)]:
            value = piece.get(field, default)
            if not terrain.number(value) or not low <= value <= high:
                raise ValueError(f'Choose {field} from {low} to {high} feet.')
        if piece.get('corner', 'mitred') not in ('mitred', 'rounded') or type(piece.get('smooth', False)) is not bool or piece.get('edging', 'none') not in ('none', 'curb'):
            raise ValueError('Choose mitred or rounded corners, a smooth curve, and none or curb edging.')
    for field, default, low, high in [('rotation', 0, -360, 360),
            *([('depth', 5, 2, 12), ('coping', 1, 0, 3)] if name == 'pool' else []),
            *([('radius', 2, .1, 100)] if round_pit else []),
            *([('height', 6, .1 if legacy_height else 2, 50 if legacy_height else 10)] if name == 'fence' else [])]:
        value = piece.get(field, default)
        if not terrain.number(value) or not low <= value <= high:
            raise ValueError(f'Choose {field} from {low} to {high}.')
    if 'style' in piece and (not isinstance(piece['style'], str) or not 1 <= len(piece['style'].strip()) <= 80):
        raise ValueError('Use a fence style of 1 to 80 characters.')
    if 'materials' in piece:
        material_slots(name, piece['materials'])
    if name == 'pool' and 'features' in piece:
        pool_features(piece)
    return points


def update(name, piece, change, lot):
    if name not in KINDS:
        raise ValueError('Choose a yard shape.')
    geometry = next((k for k in ('polygon', 'points', 'polyline') if k in piece), None)
    allowed = {geometry, 'rotation'} if geometry else {'rotation'}
    if name == 'yard_rooms':
        allowed |= {'name', 'ha_area'}
    if name in ('beds', 'hardscape', 'edges', 'pool'):
        allowed |= {'material'}
    if name == 'hardscape' and piece.get('kind') == 'path':
        allowed |= {'width', 'corner', 'radius', 'smooth', 'edging'}
    if name == 'pool':
        allowed |= {'depth', 'coping', 'features'}
    if name == 'fire_pit':
        allowed |= FIRE_FIELDS
        if piece.get('shape', 'round') == 'round':
            allowed |= {'at', 'radius'}
    if name == 'fence':
        allowed |= {'height', 'style'}
    if name in SLOTS:
        allowed |= {'materials'}
    if not change or set(change) - allowed:
        raise ValueError('Choose a supported property of this yard shape.')
    # Keep legacy read/composed references (e.g. "concrete") editable. New
    # material choices must name the kit's existing roles.
    if 'material' in change and change['material'] not in MATERIALS:
        raise ValueError('Choose an existing kit material role.')
    legacy_height = name == 'fence' and 'height' not in change
    # Switching fuel also clears a former gas-only bed colour, including when
    # the same operation rotates a drawn pit.
    if name == 'fire_pit' and change.get('fuel') == 'wood' and 'glass' not in change:
        piece.pop('glass', None)
    if 'rotation' in change and geometry and geometry not in change:
        validate(name, {**piece, **change}, legacy_height=legacy_height)
        angle = change['rotation']
        if not terrain.number(angle) or not -360 <= angle <= 360:
            raise ValueError('Choose rotation from -360 to 360.')
        points = piece[geometry]
        origin = [sum(p[i] for p in points)/len(points) for i in (0, 1)]
        if geometry == 'polygon':
            areas = [terrain.cross([0, 0], p, points[(j+1) % len(points)]) for j, p in enumerate(points)]
            area = sum(areas)
            if abs(area) > 1e-9:
                origin = [sum((p[i]+points[(j+1) % len(points)][i])*areas[j] for j, p in enumerate(points))/(3*area) for i in (0, 1)]
        previous = piece.get('rotation', 0)
        a = math.radians(angle-(previous if terrain.number(previous) else 0))
        change[geometry] = [[round(origin[0]+(p[0]-origin[0])*math.cos(a)-(p[1]-origin[1])*math.sin(a), 9),
                             round(origin[1]+(p[0]-origin[0])*math.sin(a)+(p[1]-origin[1])*math.cos(a), 9)] for p in points]
        if name == 'pool' and piece.get('features') and 'features' not in change:
            from copy import deepcopy
            change['features'] = deepcopy(piece['features'])
            for feature in change['features']:
                feature['polygon'] = [[round(origin[0]+(p[0]-origin[0])*math.cos(a)-(p[1]-origin[1])*math.sin(a), 9),
                                       round(origin[1]+(p[0]-origin[0])*math.sin(a)+(p[1]-origin[1])*math.cos(a), 9)] for p in feature['polygon']]
    if 'materials' in change:
        change = {**change, 'materials': material_slots(name, change['materials'], piece.get('materials'))}
    piece.update(change)
    if not piece.get('materials', True):
        piece.pop('materials')
    if name == 'yard_rooms' and isinstance(piece.get('name'), str):
        piece['name'] = piece['name'].strip()
    if name == 'fire_pit' and piece.get('entity') is None:
        piece.pop('entity', None)
    points = validate(name, piece, legacy_height=legacy_height)
    if name == 'pool' and 'features' in piece:
        piece['features'] = pool_features(piece)
    # Lots need not be rectangular. Check edges too, including a segment
    # crossing a concave boundary even when both endpoints are inside.
    outside = False
    if lot:
        from services.twin_terrain import inside, intersects
        outside = any(not inside(lot, p) for p in points)
        segments = list(zip(points, points[1:] + (points[:1] if geometry == 'polygon' else [])))
        for a, b in segments:
            for c, d in zip(lot, lot[1:] + lot[:1]):
                crosses = terrain.cross(a, b, c)*terrain.cross(a, b, d) < 0 and terrain.cross(c, d, a)*terrain.cross(c, d, b) < 0
                if crosses or intersects(a, b, c, d) and not all(inside(lot, p) for p in [a, b, [(a[i]+b[i])/2 for i in (0, 1)]]):
                    outside = True
        if name == 'fire_pit' and piece.get('shape', 'round') == 'round':
            radius = piece.get('radius', 2)
            outside |= any(not inside(lot, [points[0][0]+radius*math.cos(a*math.pi/32), points[0][1]+radius*math.sin(a*math.pi/32)]) for a in range(64))
        if name == 'hardscape' and piece.get('kind') == 'path':
            # Include the width, not only the centre-line endpoints, in the warning.
            radius = piece.get('width', 3)/2 + (.5 if piece.get('edging') == 'curb' else 0)
            outside |= any(not inside(lot, [p[0]+radius*math.cos(a*math.pi/8), p[1]+radius*math.sin(a*math.pi/8)]) for p in points for a in range(16))
    return 'Changed the yard shape.' + (' Warning: this shape extends outside the lot.' if outside else '')
