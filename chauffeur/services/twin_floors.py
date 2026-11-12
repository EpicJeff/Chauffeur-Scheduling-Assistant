"""Room floor references; level ceilings and wall tops never move with a room."""
import math


def offset_error(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not -10 <= value <= 10:
        return 'Choose a floor height from -10 to 10 feet.'
    return None


def opening_reference(building, wall, at):
    from services.twin_blocks import _inside
    a, b = wall.get('from'), wall.get('to')
    if a is None:
        points = {j['id']: j['at'] for j in building.get('joints', [])}
        a, b = (points[j] for j in wall['joints'])
    length = math.dist(a, b)
    if not length:
        return 0, 0
    dx, dy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    x, y = a[0] + dx * at, a[1] + dy * at
    inset = wall.get('thickness', 0) + .05
    offsets = [r.get('floor_offset_ft', 0) for r in building.get('rooms', [])
               if r.get('state') != 'ghost' and r.get('level') == wall.get('level')
               and any(_inside(r['polygon'], x - sign * dy * inset, y + sign * dx * inset)
                       for sign in (-1, 1))]
    return (max(offsets), max(offsets) - min(offsets)) if offsets else (0, 0)


def derive_openings(building):
    for opening in building.get('openings', []):
        wall = next((w for w in building['walls'] if w['id'] == opening.get('wall')), None)
        if wall is None or type(opening.get('at')) not in (int, float) or not math.isfinite(opening['at']):
            continue
        step = opening_reference(building, wall, opening['at'])[1]
        if step:
            opening['step_down_ft'] = step
        else:
            opening.pop('step_down_ft', None)
