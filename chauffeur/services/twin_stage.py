"""Stage display preference, outside house rounds and scheduler settings."""
import math

from services import storage, twin_store

KEY = 'house_twin_stage_radius_ft'
MIN_RADIUS = 30
MAX_RADIUS = 1000
LOT_MARGIN = 120


def default_stage(plan):
    """House framing bounds and lot corners, in feet with three's z = -plan y."""
    plan = plan or {}
    points = []
    for building in plan.get('buildings', []):
        angle = math.radians(building.get('rotation') or 0)
        c, s = math.cos(angle), math.sin(angle)
        x, y = building.get('position') or [0, 0]
        walls = building.get('walls') or []
        local = ([p for wall in walls for p in (wall['from'], wall['to'])] if walls else
                 [p for level in building.get('levels', []) for p in level.get('outline', [])] +
                 [p for room in building.get('rooms', []) for p in room.get('polygon', [])])
        points.extend([c * p[0] - s * p[1] + x, s * p[0] + c * p[1] + y] for p in local)
    # Keep the empty-house viewer's established centre until geometry arrives.
    centre = [(min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1)] if points else [19, 11]
    corners = (plan.get('site') or {}).get('lot') or []
    farthest = max((math.dist(centre, p) for p in corners), default=0)
    radius = min(MAX_RADIUS, max(MIN_RADIUS, farthest + LOT_MARGIN))
    return {'centre': [centre[0], -centre[1]], 'radius': radius,
            'default_radius': radius, 'radius_override': None}


def read(plan=None):
    result = default_stage(twin_store.current() if plan is None else plan)
    radius = storage.get_app_state(KEY)
    if type(radius) in (int, float) and math.isfinite(radius) and MIN_RADIUS <= radius <= MAX_RADIUS:
        result.update(radius=radius, radius_override=radius)
    return result


def save(body):
    if not isinstance(body, dict) or set(body) != {'radius'}:
        raise ValueError('Choose a stage radius or use the automatic radius.')
    radius = body['radius']
    if radius is not None and (type(radius) not in (int, float) or not math.isfinite(radius)
                               or not MIN_RADIUS <= radius <= MAX_RADIUS):
        raise ValueError('Stage radius must be between 30 and 1000 feet.')
    storage.set_app_state(KEY, radius)
    return read()
