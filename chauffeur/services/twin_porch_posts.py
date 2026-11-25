"""Hand and agent edits to porch columns, without a load-time migration."""
from copy import deepcopy
import math
import re

OPS = ('add_porch_post', 'update_porch_post', 'delete_porch_post')
ID = re.compile(r'post:[\s\S]{0,115}\Z')
MISSING = 'That post is missing.'


def post_ref(porch, index):
    return porch['columns'][index].get('id') or f"post:{porch['id']}:{index}"


def find_post(porch, ref):
    return next((i for i, c in enumerate(porch.get('columns', []))
                 if post_ref(porch, i) == ref), None)


def _fail(words):
    from services.twin_model_ops import Refused
    raise Refused(words)


def validate_target(model, op):
    building = next((b for b in model['buildings'] if b['id'] == op.get('building')), None)
    if building is None:
        _fail('That building is missing.')
    detail = next((p for p in building.get('porches_detail', []) if p['id'] == op.get('porch')), None)
    room = next((r for r in building.get('rooms', []) if r['id'] == op.get('porch') and r.get('kind') == 'porch'), None)
    if detail is None and room is None:
        _fail('That porch is missing.')
    if any(p and p.get('state') in ('ghost', 'proposal') for p in (detail, room)):
        _fail('Choose a settled porch; ghost and proposal porches cannot edit posts.')
    index = None
    if op['op'] != 'add_porch_post':
        index = find_post(detail or {}, op.get('post'))
        if index is None:
            _fail(MISSING)
    return building, detail, room, index


def common_size(porch):
    counts = {}
    for c in porch.get('columns', []):
        counts[c['size']] = counts.get(c['size'], 0) + 1
    return max(counts, key=counts.get) if counts else .5


def _project(p, a, b):
    d = [b[i]-a[i] for i in (0, 1)]
    length2 = sum(v*v for v in d)
    t = max(0, min(1, sum((p[i]-a[i])*d[i] for i in (0, 1))/length2)) if length2 else 0
    q = [a[i]+t*d[i] for i in (0, 1)]
    return math.dist(p, q), t, q


def default_at(building, porch, size):
    """Longest unoccupied open edge interval; stable edge/order ties."""
    room = next((r for r in building.get('rooms', []) if r['id'] == porch['id']), None)
    polygon = (room or porch)['polygon']
    level = (room or porch).get('level') or building['levels'][0]['id']
    joints = {j['id']: j['at'] for j in building.get('joints', [])}
    walls = []
    for w in building.get('walls', []):
        if w.get('kind') == 'separator' or w.get('state') == 'ghost' or w.get('level') != level:
            continue
        a, b = (joints.get(j) for j in w.get('joints', [None, None]))
        if a is not None and b is not None:
            walls.append((a, b))
    winding = 1 if sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(polygon, polygon[1:]+polygon[:1])) > 0 else -1
    best = None
    for a, b in zip(polygon, polygon[1:]+polygon[:1]):
        length = math.dist(a, b)
        if not length:
            continue
        spans = [(0, 1)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        for c, d in walls:
            if any(abs((p[0]-a[0])*dy-(p[1]-a[1])*dx)/length >= .05 for p in (c,d)):
                continue
            lo, hi = sorted(max(0, min(1, ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length**2)) for p in (c,d))
            spans = [(s,e) for start,end in spans for s,e in ((start,min(end,lo)),(max(start,hi),end)) if e-s > 1e-9]
        gaps = []
        for start, end in spans:
            cuts = [start, end]
            for c in porch.get('columns', []):
                distance, t, _ = _project(c['at'], a, b)
                if distance <= c['size']/2 + .1 and start < t < end:
                    cuts.append(t)
            cuts.sort()
            gaps.extend(zip(cuts,cuts[1:]))
        for lo, hi in gaps:
            gap = (hi-lo)*length
            if best is None or gap > best[0]:
                t = (lo+hi)/2
                best = gap, [a[0]+t*(b[0]-a[0])-winding*(b[1]-a[1])/length*size/2,
                             a[1]+t*(b[1]-a[1])+winding*(b[0]-a[0])/length*size/2]
    if best is None:
        _fail('This porch has no open edge for a post; choose a position.')
    return best[1]


def _used_ids(building, *, derived=True):
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get('id'), str):
                yield value['id']
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)
    return set(walk(building)) | ({post_ref(p,i) for p in building.get('porches_detail', []) for i in range(len(p.get('columns', [])))} if derived else set())


def mint_columns(building, detail):
    used = _used_ids(building, derived=False)
    pending = []
    for i,column in enumerate(detail.get('columns', [])):
        if not column.get('id'):
            ref = f"post:{detail['id']}:{i}"
            if ref in used:
                _fail('That post id is already in use.')
            used.add(ref)
            pending.append((column,ref))
    for column,ref in pending:
        column['id'] = ref


def next_id(detail):
    used = {c.get('id') for c in detail.get('columns', [])}
    n = len(detail.get('columns', []))
    while f"post:{detail['id']}:{n}" in used:
        n += 1
    return f"post:{detail['id']}:{n}"


def apply_op(model, op, actor='person'):
    from services.twin_model_ops import _person
    building, detail, room, index = validate_target(model, op)
    kind = op['op']
    if kind == 'update_porch_post' and not any(k in op for k in ('at', 'size')):
        _fail('Choose a post position or size to change.')
    if 'size' in op and (type(op['size']) not in (int, float) or not math.isfinite(op['size']) or not .05 <= op['size'] <= 3):
        _fail('Choose a post size from 0.05 to 3 feet.')
    if 'at' in op and (not isinstance(op['at'], (list, tuple)) or len(op['at']) != 2
                       or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e5 for v in op['at'])):
        _fail('Choose a finite post position.')
    used = _used_ids(building)
    if kind == 'add_porch_post':
        if len((detail or {}).get('columns', [])) >= 40:
            _fail('A porch can have at most 40 posts.')
        if 'id' in op:
            if not isinstance(op['id'], str) or not ID.fullmatch(op['id']):
                _fail('Choose a post id starting with post: and at most 120 characters.')
            if op['id'] in used:
                _fail('That post id is already in use.')
            used.add(op['id'])
    if detail is None:
        detail = dict(id=room['id'], level=room['level'], polygon=deepcopy(room['polygon']),
                      floor=next(l['elevation'] for l in building['levels'] if l['id'] == room['level']), columns=[])
        building.setdefault('porches_detail', []).append(detail)
    detail.setdefault('columns', [])
    mint_columns(building, detail)
    if kind == 'add_porch_post':
        size = op.get('size', common_size(detail))
        if type(size) not in (int, float) or not .05 <= size <= 3:
            _fail('Choose a post size from 0.05 to 3 feet.')
        at = list(op['at']) if 'at' in op else default_at(building, detail, size)
        ref = op['id'] if 'id' in op else next_id(detail)
        if 'id' not in op and ref in used:
            _fail('That post id is already in use.')
        detail['columns'].append(dict(id=ref, at=at, size=size))
    elif kind == 'delete_porch_post':
        detail['columns'].pop(index)
    else:
        for key in ('at', 'size'):
            if key in op:
                detail['columns'][index][key] = deepcopy(op[key])
    _person(detail)
    return {'add_porch_post':'Added the post.', 'update_porch_post':'Changed the post.', 'delete_porch_post':'Deleted the post.'}[kind]


FOLLOW_OPS = ('move_room', 'move_joint', 'move_joints', 'move_wall')


def corner_targets(before, after, old, room):
    """Polygon order need not agree with a room's graph cycle."""
    a, b = old['polygon'], room['polygon']
    candidates = [b[i:]+b[:i] for i in range(len(b))]
    candidates += [list(reversed(c)) for c in candidates]
    fallback = (min(candidates, key=lambda c: sum(math.dist(p,q)**2 for p,q in zip(a,c)))
                if len(a) == len(b) else
                [min((_project(p,c,d) for c,d in zip(b,b[1:]+b[:1])), key=lambda h:h[0])[2] for p in a])
    positions = {j['id']: j['at'] for j in after.get('joints', [])}
    joints = [j for j in before.get('joints', []) if j['id'] in old.get('joints', [])]
    return [positions[joint['id']] if joint and joint['id'] in positions else fallback[i]
            for i,p in enumerate(a)
            for joint in [next((j for j in joints if math.dist(p,j['at']) <= .01), None)]]


def follow_posts(before, after):
    """Transport existing posts once, only after explicit corner moves."""
    from services.twin_model_ops import _person
    old_rooms = {r['id']: r for r in before.get('rooms', []) if r.get('kind') == 'porch'}
    for room in after.get('rooms', []):
        old = old_rooms.get(room['id'])
        if not old or room.get('kind') != 'porch':
            continue
        a, b = old['polygon'], room['polygon']
        # A rotated cycle or an inserted collinear corner is the same outline.
        if all(min(_project(p,c,d)[0] for c,d in zip(q,q[1:]+q[:1])) <= .01
               for points,q in ((a,b),(b,a)) for p in points):
            continue
        detail = next((p for p in after.get('porches_detail', []) if p['id'] == room['id']), None)
        if detail is None:
            continue
        positions = {j['id']:j['at'] for j in before.get('joints', [])}
        cycle = [positions.get(j) for j in old.get('joints', [])]
        if len(cycle) >= 3 and all(p is not None for p in cycle):
            a = cycle
        targets = corner_targets(before, after, {**old, 'polygon':a}, room)
        vectors = [[q[i]-p[i] for i in (0,1)] for p,q in zip(a,targets)]
        translation = all(math.dist(v,vectors[0]) <= 1e-8 for v in vectors)
        moved = False
        for column in detail.get('columns', []):
            point = column['at']
            if translation:
                by = vectors[0]
            else:
                corner = min(range(len(a)), key=lambda i:math.dist(point,a[i]))
                if math.dist(point,a[corner]) <= 1 + column['size']/2:
                    by = vectors[corner]
                else:
                    hits = [_project(point,c,d) for c,d in zip(a,a[1:]+a[:1])]
                    edge = min(range(len(hits)), key=lambda i:hits[i][0])
                    distance,t,_ = hits[edge]
                    if distance > 4:
                        continue
                    end = (edge+1)%len(a)
                    displacement = [(1-t)*vectors[edge][i]+t*vectors[end][i] for i in (0,1)]
                    dx,dy = a[end][0]-a[edge][0],a[end][1]-a[edge][1]
                    length = math.hypot(dx,dy)
                    normal = [-dy/length,dx/length] if length else [0,0]
                    amount = sum(displacement[i]*normal[i] for i in (0,1))
                    by = [amount*n for n in normal]
            if math.hypot(*by) > .01:
                column['at'] = [point[i]+by[i] for i in (0,1)]
                moved = True
        if moved:
            detail.setdefault('read_geometry', {'polygon':deepcopy(detail.get('polygon',a))})
            detail['polygon'] = deepcopy(b)
            _person(detail)
