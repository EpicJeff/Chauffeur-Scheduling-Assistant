"""Entity-owned light fixtures, in lot feet; no Home Assistant dependency.

Snaps name a host and two lot endpoints, never an edge index. Resolved heights
are absolute in resolve_snap and converted to the fixture's ref by normalize.
"""
from copy import deepcopy
import hashlib
import json
import math
import re
from uuid import UUID, uuid4

from services import twin_terrain as terrain

DEFAULT_OUTPUT_LM = 503
MAX_FIXTURES = 64
MAX_OUTPUT_LM = 1e6
MAX_SHARE = 1e6
OPS = ('add_light_fixture', 'update_light_fixture', 'delete_light_fixture', 'set_light_output', 'set_camera_view', 'set_climate_zone')
_SHAPES = {
    'point': {'at', 'offset_ft'},
    'spot': {'at', 'aim', 'cone_deg', 'softness', 'offset_ft'},
    'line': {'path', 'snap', 'anchors', 'facing', 'width_in', 'detached', 'offset_ft'},
    'area': {'at', 'size_ft', 'facing', 'rotation_deg', 'offset_ft'},
}
_ANCHOR_KINDS = ('building', 'wall', 'roof', 'floor', 'room', 'porch', 'stair',
                 'opening', 'item', 'fixture', 'light', 'anchor', 'solar_zone',
                 'retaining_wall', 'terrace', 'hardscape', 'fence', 'pool', 'spa', 'ledge', 'steps')


def _number(value, label, low=-1e5, high=1e5):
    valid = type(value) in (int, float) and low <= value <= high
    try:
        valid = valid and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f'Choose a finite {label} from {low} to {high}.')
    return value


def _vector(value, n, label):
    if not isinstance(value, (list, tuple)) or len(value) != n:
        raise ValueError(f'{label} needs {n} coordinates.')
    return [_number(v, label) for v in value]


def _entity(value):
    if not isinstance(value, str) or not re.fullmatch(r'(light|switch|media_player)\.[a-z0-9_]+', value):
        raise ValueError('Choose a light, switch or media_player entity.')
    return value


def _snap(value):
    if not isinstance(value, dict) or set(value) - {'host', 'edge', 't0', 't1'}:
        raise ValueError('Choose a snap host, edge endpoints and t0/t1.')
    host, edge = value.get('host'), value.get('edge')
    if (not isinstance(host, dict) or set(host) != {'kind', 'id'}
            or host['kind'] not in ('retaining_wall', 'hardscape', 'fence', 'step', 'wall', 'pool', 'spa')
            or not isinstance(host['id'], str) or not host['id']):
        raise ValueError('Choose a stable snap host kind and id.')
    if not isinstance(edge, dict) or set(edge) != {'from', 'to'}:
        raise ValueError('A snapped edge needs from/to endpoints, not an index.')
    edge = {key: _vector(edge[key], 2, 'Edge endpoint') for key in ('from', 'to')}
    if math.dist(edge['from'], edge['to']) <= 1e-8:
        raise ValueError('Choose a nonzero edge.')
    t0, t1 = (_number(value.get(k, d), k, 0, 1) for k, d in (('t0', 0), ('t1', 1)))
    if t0 == t1:
        raise ValueError('A snapped run must have length.')
    return {'host': dict(host), 'edge': edge, 't0': t0, 't1': t1}


def _anchors(value, path):
    if not isinstance(value, list) or len(value) != len(path):
        raise ValueError('Anchors must be a list with one entry per path point.')
    result = []
    for entry in value:
        if entry is None:
            result.append(None)
            continue
        if not isinstance(entry, dict) or set(entry) != {'host', 'local'}:
            raise ValueError('An anchor needs a stable host and local coordinates.')
        host = entry['host']
        if (not isinstance(host, dict) or set(host) - {'kind', 'id', 'building'}
                or host.get('kind') not in _ANCHOR_KINDS
                or not isinstance(host.get('id'), str) or not host['id']
                or 'building' in host and (not isinstance(host['building'], str) or not host['building'])):
            raise ValueError('Choose a stable anchor host kind, id and optional building id.')
        result.append({'host': dict(host), 'local': _vector(entry['local'], 3, 'Anchor local point')})
    return result


def validate(fixture):
    """Return a fresh canonical fixture, or raise ValueError for malformed data."""
    if not isinstance(fixture, dict) or not isinstance(fixture.get('shape'), str) or fixture['shape'] not in _SHAPES:
        raise ValueError('Choose point, spot, line or area.')
    f = deepcopy(fixture)
    # Context status is derived from the current house, never authored data.
    f.pop('orphaned', None)
    f.pop('orphan_reason', None)
    shape = f['shape']
    if set(f) - {'id', 'shape', 'share', 'ref', 'building', 'level'} - _SHAPES[shape]:
        raise ValueError('Choose supported fixture properties.')
    fid = f.get('id')
    try:
        if not isinstance(fid, str) or not fid.startswith('fixture:'):
            raise ValueError()
        if str(UUID(fid[8:])) != fid[8:]:
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError('A fixture needs a canonical fixture:<uuid> id.') from None
    if f.get('ref') not in ('floor', 'ground', 'absolute'):
        raise ValueError('Choose a floor, ground or absolute vertical reference.')
    if f['ref'] == 'floor':
        if any(not isinstance(f.get(k), str) or not f[k] for k in ('building', 'level')):
            raise ValueError('A floor fixture needs its building and level.')
    else:
        f.pop('building', None)
        f.pop('level', None)
    if 'share' in f:
        _number(f['share'], 'share', 0, MAX_SHARE)
    if 'offset_ft' in f:
        f['offset_ft'] = _number(f['offset_ft'], 'vertical offset in feet', -50, 50)
    if shape != 'line':
        f['at'] = _vector(f.get('at'), 3, 'Position')
    if shape == 'spot':
        f['aim'] = _vector(f.get('aim'), 3, 'Aim')
        if math.dist(f['at'], f['aim']) <= 1e-8:
            raise ValueError('Aim away from the fixture.')
        f['cone_deg'] = _number(f.get('cone_deg', 90), 'cone degrees', 10, 160)
        f['softness'] = _number(f.get('softness', .3), 'softness', 0, 1)
    if shape == 'line':
        path = f.get('path')
        if not isinstance(path, list) or not 2 <= len(path) <= 64:
            raise ValueError('A line needs 2-64 points.')
        f['path'] = [_vector(p, 3, 'Path point') for p in path]
        if any(math.dist(a, b) <= 1e-8 for a, b in zip(f['path'], f['path'][1:])):
            raise ValueError('Consecutive line points must differ.')
        if 'anchors' in f:
            if f.get('snap') is not None:
                raise ValueError('Choose point anchors or a whole-edge snap, not both.')
            f['anchors'] = _anchors(f['anchors'], f['path'])
        f['facing'] = f.get('facing', 'down')
        if f['facing'] not in ('down', 'out', 'up', 'in'):
            raise ValueError('Choose down, out, up or in for a line.')
        f['width_in'] = _number(f.get('width_in', .5), 'line width in inches', .25, 2)
        if type(f.get('detached', False)) is not bool:
            raise ValueError('detached must be true or false.')
        f['detached'] = f.get('detached', False)
        if f.get('snap') is not None:
            f['snap'] = _snap(f['snap'])
        else:
            f.pop('snap', None)
            f['detached'] = False
    if shape == 'area':
        f['size_ft'] = _vector(f.get('size_ft'), 2, 'Area size')
        if min(f['size_ft']) <= 0:
            raise ValueError('An area needs positive width and height.')
        facing = f.get('facing', 'down')
        if isinstance(facing, str):
            if facing not in ('down', 'out', 'up'):
                raise ValueError('Choose down, out, up or a normal for an area.')
        else:
            facing = _vector(facing, 3, 'Facing normal')
            length = math.sqrt(sum(v*v for v in facing))
            if length <= 1e-8:
                raise ValueError('Facing must be a nonzero normal.')
            if not math.isclose(length, 1, rel_tol=0, abs_tol=1e-12):
                facing = [v / length for v in facing]
        f['facing'] = facing
        f['rotation_deg'] = _number(f.get('rotation_deg', 0), 'rotation degrees') % 360
    return f


def _pieces(value):
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


def _world(building, point):
    from services.twin_register import to_world
    return to_world(building, point)


def _path_outline(path):
    """The path_shapes.js centreline and mitred boundaries, in lot feet."""
    def add(a, b):
        return [a[i]+b[i] for i in (0, 1)]

    def sub(a, b):
        return [a[i]-b[i] for i in (0, 1)]

    def mul(a, k):
        return [v*k for v in a]

    def unit(a):
        return mul(a, 1/(math.hypot(*a) or 1))

    def cross(a, b):
        return a[0]*b[1]-a[1]*b[0]

    def normal(a):
        return [-a[1], a[0]]

    raw = path.get('points', [])
    ps = [p for i, p in enumerate(raw) if not i or math.dist(p, raw[i-1]) > 1e-8]
    if len(ps) < 2:
        return []
    if path.get('smooth'):
        dense, knots = [ps[0]], set()
        for i in range(len(ps)-1):
            a, b, c, d = ps[max(0, i-1)], ps[i], ps[i+1], ps[min(len(ps)-1, i+2)]
            n = max(8, math.ceil((math.dist(b, a)+math.dist(c, b)+math.dist(d, c))*4))
            for j in range(1, n+1):
                t = j/n
                dense.append(c if j == n else [.5*(2*b[k]+(-a[k]+c[k])*t+(2*a[k]-5*b[k]+4*c[k]-d[k])*t*t
                                                   +(-a[k]+3*b[k]-3*c[k]+d[k])*t*t*t) for k in (0, 1)])
            knots.add(len(dense)-1)
        out, remaining, previous = [dense[0]], 1, dense[0]
        for i, target in enumerate(dense[1:], 1):
            gap = math.dist(target, previous)
            while gap >= remaining:
                previous = add(previous, mul(unit(sub(target, previous)), remaining))
                out.append(previous)
                gap, remaining = math.dist(target, previous), 1
            remaining -= gap
            previous = target
            if i in knots:
                if math.dist(out[-1], target) > 1e-8:
                    out.append(target)
                remaining = 1
        if math.dist(out[-1], ps[-1]) > 1e-8:
            out.append(ps[-1])
        ps = out
    elif path.get('corner') == 'rounded' and len(ps) >= 3:
        out = [ps[0]]
        for i in range(1, len(ps)-1):
            p = ps[i]
            incoming, outgoing = unit(sub(p, ps[i-1])), unit(sub(ps[i+1], p))
            turn = math.atan2(cross(incoming, outgoing), sum(a*b for a, b in zip(incoming, outgoing)))
            if abs(turn) < 1e-5 or abs(turn) > math.pi-.01:
                out.append(p)
                continue
            tangent = math.tan(abs(turn)/2)
            cut = min(path.get('radius', path.get('width', 3))*tangent, math.dist(p, ps[i-1])*.49, math.dist(ps[i+1], p)*.49)
            radius = cut/tangent
            start = sub(p, mul(incoming, cut))
            centre = add(start, mul(normal(incoming), math.copysign(radius, turn)))
            angle = math.atan2(start[1]-centre[1], start[0]-centre[0])
            n = max(2, math.ceil(abs(turn)*radius/.5))
            out.extend(add(centre, [math.cos(angle+turn*j/n)*radius, math.sin(angle+turn*j/n)*radius]) for j in range(n+1))
        ps = [*out, ps[-1]]
    half = path.get('width', 3)/2

    def side(sign):
        out = []
        for i, p in enumerate(ps):
            a, b = unit(sub(p, ps[max(0, i-1)])), unit(sub(ps[min(len(ps)-1, i+1)], p))
            if i == 0 or i == len(ps)-1:
                out.append(add(p, mul(normal(b if i == 0 else a), half*sign)))
                continue
            na, nb, den = mul(normal(a), half*sign), mul(normal(b), half*sign), cross(a, b)
            if abs(den) < 1e-8:
                out.extend([add(p, nb)] if sum(x*y for x, y in zip(a, b)) > 0 else [add(p, na), add(p, nb)])
                continue
            mitre = add(na, mul(a, cross(sub(nb, na), b)/den))
            out.extend([add(p, mitre)] if math.hypot(*mitre) <= half*2 else [add(p, na), add(p, nb)])
        return out
    return side(1) + list(reversed(side(-1)))


def _host_edges(model, host):
    """Yield (from xyz, to xyz) at host tops in absolute lot feet."""
    kind, hid = host['kind'], host['id']
    site = model.get('site', {})
    if kind in ('wall', 'step'):
        matches = [(b, p) for b in model.get('buildings', []) for p in b.get('walls' if kind == 'wall' else 'stairs', [])
                   if p.get('id') == hid and p.get('state') not in ('ghost', 'proposal')]
        if len(matches) != 1:
            return []
        b, p = matches[0]
        level = next((l for l in b['levels'] if l['id'] == p.get('level')), None)
        if level is None:
            return []
        base = b.get('base', 0) + level['elevation']
        if kind == 'wall':
            joints = {j['id']: j['at'] for j in b.get('joints', [])}
            if len(p.get('joints', [])) != 2 or any(j not in joints for j in p['joints']):
                return []
            ends = [_world(b, joints[j]) for j in p['joints']]
            return [([*ends[0], base + p.get('height', level.get('ceiling', 9))],
                     [*ends[1], base + p.get('height', level.get('ceiling', 9))])]
        if (any(not isinstance(p.get(k), list) or len(p[k]) != 2 or not all(terrain.number(v) for v in p[k]) for k in ('from', 'to'))
                or not terrain.number(p.get('width')) or p['width'] <= 0 or not terrain.number(p.get('rise_to'))):
            return []
        a, z = p['from'], p['to']
        length, risers = math.dist(a, z), p.get('risers', 0)
        if length <= 1e-8 or type(risers) not in (int, float) or not 1 <= risers <= 1000:
            return []
        normal = [-(z[1]-a[1])/length, (z[0]-a[0])/length]
        result = []
        for i in range(int(risers)):
            # The leading (downhill) edge of each rendered tread.
            centre = [a[j] + (z[j]-a[j])*i/risers for j in (0, 1)]
            ends = [_world(b, [centre[j] + sign*normal[j]*p['width']/2 for j in (0, 1)]) for sign in (-1, 1)]
            height = base + (p['rise_to']-level['elevation'])*(i+1)/risers
            result.append(([*ends[0], height], [*ends[1], height]))
        return result
    if kind in ('pool', 'spa'):
        # Coping tops, at the heights the renderer builds them (twin_yard.js, pool_features.js).
        pool = site.get('pool') or {}
        outline = pool.get('polygon') or []
        if len(outline) < 3:
            return []
        top = terrain.ground_at(site.get('terraces', []), outline[0]) + (pool.get('elevation') or 0)
        if kind == 'pool':
            if hid != (pool.get('id') or 'pool:0'):
                return []
            coping = pool.get('coping')
            points, top = outline, top + (.45 if (1 if coping is None else coping) > 0 else .3)
        else:
            spas = [f for f in pool.get('features') or []
                    if f.get('kind') == 'spa' and f.get('id') == hid and len(f.get('polygon') or []) >= 3]
            if len(spas) != 1:
                return []
            spa, points = spas[0], spas[0]['polygon']
            raise_in = spa.get('raise_in')
            top += .45 + ((12 if raise_in is None else raise_in) / 12 if (spa.get('mode') or 'raised') == 'raised' else 0)
        return [([*a, top], [*b, top]) for a, b in zip(points, points[1:] + points[:1])]
    name = {'retaining_wall': 'terraces', 'hardscape': 'hardscape', 'fence': 'fence'}.get(kind)
    matches = [p for p in _pieces(site.get(name)) if p.get('id') == hid]
    if len(matches) != 1:
        return []
    p = matches[0]
    points = p.get('polygon') or p.get('polyline') or p.get('points') or []
    closed = 'polygon' in p
    if kind == 'hardscape' and p.get('kind') == 'path':
        points, closed = _path_outline(p), True
    pairs = list(zip(points, points[1:] + points[:1] if closed else points[1:]))
    result = []
    for i, (a, b) in enumerate(pairs):
        if kind == 'retaining_wall':
            edge = p.get('edges', [])[i] if i < len(p.get('edges', [])) else {}
            if edge.get('edge') != 'sharp' or not edge.get('wall'):
                continue
            height = p['height'] + edge['wall'].get('above_in', 0)/12
            heights = [height, height]
        else:
            heights = [p.get('elevation') if p.get('elevation') is not None else terrain.ground_at(site.get('terraces', []), q) for q in (a, b)]
            if kind == 'fence':
                heights = [h + p.get('height', 6) for h in heights]
        result.append(([*a, heights[0]], [*b, heights[1]]))
    return result


def _match(edges, snap):
    a, b = snap['edge']['from'], snap['edge']['to']
    candidates = []
    for start, end in edges:
        for p, q in ((start, end), (end, start)):
            distances = (math.dist(a, p[:2]), math.dist(b, q[:2]))
            if max(distances) <= .5:
                candidates.append((sum(distances), p, q))
    if not candidates:
        return None
    _, p, q = min(candidates, key=lambda row: row[0])
    return p, q


def resolve_snap(model, snap):
    """Return the endpoint-matched sub-path in absolute xyz feet, or None.

    Return the host edge line itself (cap top, surface edge, etc.), with no
    facing offset. Task 2's emitter resolver applies the mounting offset per
    facing; down/out/up/in share the stored attachment path here.
    """
    snap = _snap(snap)
    matched = _match(_host_edges(model, snap['host']), snap)
    if matched is None:
        return None
    p, q = matched
    return [[p[i] + (q[i]-p[i])*t for i in range(3)] for t in (snap['t0'], snap['t1'])]


def _reference(model, f, point):
    if f['ref'] == 'ground':
        return terrain.ground_at(model.get('site', {}).get('terraces', []), point[:2])
    if f['ref'] == 'floor':
        building = next((b for b in model.get('buildings', []) if b['id'] == f['building']), None)
        level = next((l for l in (building or {}).get('levels', []) if l['id'] == f['level']), None)
        if level is None:
            raise ValueError('Choose an existing fixture building and level.')
        return building.get('base', 0) + level['elevation']
    return 0


def _context_error(model, f):
    """Describe missing floor/lot context without rejecting a stored fixture."""
    from services.twin_site_shapes import _contained
    lot = model.get('site', {}).get('lot')
    points = f['path'] if f['shape'] == 'line' else [f['at']]
    try:
        _reference(model, f, points[0])
    except ValueError as exc:
        return str(exc)
    if f['shape'] == 'area':
        x, y, z = f['at']
        w, h = f['size_ft']
        angle = math.radians(f['rotation_deg'])
        c, s = math.cos(angle), math.sin(angle)
        points = [[x + dx*c - dy*s, y + dx*s + dy*c, z]
                  for dx, dy in ((-w/2, -h/2), (w/2, -h/2), (w/2, h/2), (-w/2, h/2))]
        points.append(points[0])
    # Check the open polyline, without inventing a closing edge across a notch.
    outside = lot and any(not terrain.inside(lot, p[:2]) for p in points)
    if lot and not outside:
        outside = any(not _contained(lot, [a[:2], b[:2]]) for a, b in zip(points, points[1:]) if a[:2] != b[:2])
    if outside:
        return 'Fixture positions and paths must stay inside the lot.'
    return None


def _in_lot(model, f):
    """Reject invalid context only for the fixture being added or edited."""
    if reason := _context_error(model, f):
        raise ValueError(reason)


def _resolve(model, f):
    if f['shape'] == 'line' and 'snap' in f:
        path = resolve_snap(model, f['snap'])
        if path is None:
            f['detached'] = True
        else:
            try:
                resolved = {**f, 'path': [[*p[:2], p[2] - _reference(model, f, p)] for p in path]}
                if reason := _context_error(model, resolved):
                    raise ValueError(reason)
            except ValueError:
                # Host/floor removal or leaving the lot cannot erase a run.
                f['detached'] = True
            else:
                f['path'] = resolved['path']
                f['detached'] = False


def normalize(model, notes):
    """Drop structurally invalid fixtures; retain context orphans with reasons."""
    if 'climate_zones' in model:
        kept = {}
        raw = model['climate_zones']
        if not isinstance(raw, dict):
            notes.append('Dropped invalid climate_zones; expected an entity map.')
            raw = {}
        ids = {r['id'] for b in model.get('buildings', []) for r in b.get('rooms', [])}
        ids.update(r['id'] for r in model.get('site', {}).get('yard_rooms', []))
        for entity, value in raw.items():
            try:
                zone = validate_climate_zone(entity, value)
                if zone is not None:
                    kept[entity] = {**zone, **{key: [r for r in zone[key] if r in ids] for key in ('rooms', 'except')}}
            except ValueError as exc:
                notes.append(f'Dropped climate zone for {entity}: {exc}')
        model['climate_zones'] = kept
    if 'camera_views' in model:
        kept = {}
        raw = model['camera_views']
        if not isinstance(raw, dict):
            notes.append('Dropped invalid camera_views; expected an entity map.')
            raw = {}
        for entity, value in raw.items():
            try:
                value = validate_camera_view(entity, value)
                if len(kept) >= 64:
                    raise ValueError('A house can have at most 64 camera views.')
                kept[entity] = value
            except ValueError as exc:
                notes.append(f'Dropped camera view for {entity}: {exc}')
        model['camera_views'] = kept
    if 'light_fixtures' in model:
        raw = model['light_fixtures']
        kept = {}
        if not isinstance(raw, dict):
            notes.append('Dropped invalid light_fixtures; expected an entity map.')
            raw = {}
        ids = set()
        for entity, fixtures in raw.items():
            try:
                _entity(entity)
                if not isinstance(fixtures, list):
                    raise ValueError('Expected a fixture list.')
            except ValueError as exc:
                notes.append(f'Dropped fixtures for {entity}: {exc}')
                continue
            rows = []
            for fixture in fixtures:
                try:
                    f = validate(fixture)
                    if f['id'] in ids or len(rows) >= MAX_FIXTURES:
                        raise ValueError('Duplicate fixture id or more than 64 fixtures.')
                except ValueError as exc:
                    notes.append(f'Dropped a fixture for {entity}: {exc}')
                    continue
                _resolve(model, f)
                if reason := _context_error(model, f):
                    f.update(orphaned=True, orphan_reason=reason)
                rows.append(f)
                ids.add(f['id'])
            if rows:
                kept[entity] = rows
        model['light_fixtures'] = kept
    if 'light_fixtures_meta' in model:
        raw = model['light_fixtures_meta']
        kept = {}
        if not isinstance(raw, dict):
            notes.append('Dropped invalid light_fixtures_meta; expected an entity map.')
            raw = {}
        for entity, value in raw.items():
            try:
                _entity(entity)
                if not isinstance(value, dict) or set(value) - {'output_lm'}:
                    raise ValueError('Expected output_lm metadata.')
                kept[entity] = {'output_lm': _number(value.get('output_lm', DEFAULT_OUTPUT_LM), 'output in lumens', 0, MAX_OUTPUT_LM)}
            except ValueError as exc:
                notes.append(f'Dropped fixture metadata for {entity}: {exc}')
        model['light_fixtures_meta'] = kept


def signature(entity_id, fixtures):
    """Stable SHA-256 of resolved fixture data (or a live output envelope)."""
    payload = json.dumps([entity_id, fixtures], sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def live_layout(model):
    """Maps for GET /api/house/live, including output in the entity signature."""
    fixtures = deepcopy(model.get('light_fixtures', {}))
    meta = deepcopy(model.get('light_fixtures_meta', {}))
    for entity in fixtures:
        meta.setdefault(entity, {'output_lm': DEFAULT_OUTPUT_LM})
    return {'light_fixtures': fixtures, 'light_fixtures_meta': meta, 'camera_views': deepcopy(model.get('camera_views', {})),
            'climate_zones': deepcopy(model.get('climate_zones', {})),
            'light_fixtures_signatures': {eid: signature(eid, {'fixtures': rows, **meta[eid]}) for eid, rows in fixtures.items()}}


def validate_camera_view(entity, value):
    if not isinstance(entity, str) or not re.fullmatch(r'camera\.[a-z0-9_]+', entity):
        raise ValueError('Choose a camera entity.')
    if not isinstance(value, dict) or set(value) - {'at', 'aim', 'fov_deg'}:
        raise ValueError('Choose a camera aim and field of view.')
    aim = _vector(value.get('aim'), 3, 'aim')
    if math.hypot(*aim) > 2000:
        raise ValueError('Camera aim must stay within 2000 feet of the lot origin.')
    return {'aim': aim, 'fov_deg': _number(value.get('fov_deg', 90), 'field of view', 10, 160)}


def validate_climate_zone(entity, value):
    if not isinstance(entity, str) or not re.fullmatch(r'climate\.[a-z0-9_]+', entity):
        raise ValueError('Choose a climate entity.')
    if not isinstance(value, dict) or 'scope' not in value or set(value) - {'scope', 'rooms', 'except'}:
        raise ValueError('Choose a climate scope, rooms and except list.')
    if value['scope'] is not None and value['scope'] not in ('house', 'floor', 'rooms'):
        raise ValueError('Choose house, floor or rooms.')
    result = {'scope': value['scope']}
    for key in ('rooms', 'except'):
        rows = value.get(key, [])
        if not isinstance(rows, list) or len(rows) > 64 or any(not isinstance(r, str) for r in rows):
            raise ValueError('Choose at most 64 room ids per list.')
        result[key] = list(dict.fromkeys(rows))
    return result if value['scope'] is not None else None


def apply_op(model, op):
    """Mutate the private editor model; validation errors abort its one round."""
    kind = op['op']
    if kind == 'set_climate_zone':
        entity = op.get('entity')
        value = validate_climate_zone(entity, {key: op[key] for key in ('scope', 'rooms', 'except') if key in op})
        zones = model.setdefault('climate_zones', {})
        if value is None:
            zones.pop(entity, None)
        else:
            zones[entity] = value
        return 'Changed the climate zone.'
    if kind == 'set_camera_view':
        entity = op.get('entity_id')
        value = validate_camera_view(entity, op.get('view'))
        views = model.setdefault('camera_views', {})
        if entity not in views and len(views) >= 64:
            raise ValueError('A house can have at most 64 camera views.')
        views[entity] = value
        return 'Changed the camera view.'
    entity = _entity(op.get('entity_id'))
    if kind == 'set_light_output':
        value = _number(op.get('output_lm'), 'output in lumens', 0, MAX_OUTPUT_LM)
        model.setdefault('light_fixtures_meta', {})[entity] = {'output_lm': value}
        return 'Changed the light output.'
    fixtures = model.setdefault('light_fixtures', {}).setdefault(entity, [])
    if kind == 'add_light_fixture':
        if len(fixtures) >= MAX_FIXTURES:
            raise ValueError('An entity can have at most 64 fixtures.')
        value = deepcopy(op.get('fixture'))
        if isinstance(value, dict):
            value.setdefault('id', 'fixture:' + str(uuid4()))
        value = validate(value)
        if any(f['id'] == value['id'] for rows in model['light_fixtures'].values() for f in rows):
            raise ValueError('That fixture id already exists.')
    else:
        previous = next((f for f in fixtures if f['id'] == op.get('id')), None)
        if previous is None:
            raise ValueError('That light fixture is missing.')
        if kind == 'delete_light_fixture':
            fixtures.remove(previous)
            if not fixtures:
                del model['light_fixtures'][entity]
            return 'Deleted the light fixture.'
        change = op.get('change')
        if not isinstance(change, dict) or 'id' in change:
            raise ValueError('Choose fixture changes; the id stays fixed.')
        baseline = previous
        if 'shape' in change and change['shape'] != previous['shape']:
            # An explicit shape change keeps common fields and compatible
            # geometry, but cannot carry stale spot/line parameters with it.
            allowed = _SHAPES.get(change['shape'], set()) if isinstance(change['shape'], str) else set()
            baseline = {k: v for k, v in previous.items() if k in {'id', 'shape', 'share', 'ref', 'building', 'level'} | allowed}
        candidate = {**baseline, **change}
        if 'share' in change and change['share'] is None:
            candidate.pop('share', None)
        if 'anchors' in change and change['anchors'] is None:
            candidate.pop('anchors', None)
        value = validate(candidate)
    _in_lot(model, value)
    _resolve(model, value)
    _in_lot(model, value)
    if kind == 'add_light_fixture':
        fixtures.append(value)
    else:
        fixtures[fixtures.index(previous)] = value
    return 'Added the light fixture.' if kind == 'add_light_fixture' else 'Changed the light fixture.'


def _building_base(model, building):
    """The rendered buildingBase, including the auto-foundation ground samples."""
    if building.get('foundation', {}).get('mode') != 'auto':
        return building.get('base', 0)
    pads = model.get('site', {}).get('terraces', [])
    first = min(building.get('levels', []), key=lambda l: l['elevation'], default={})
    outline = first.get('outline', [])
    if len(outline) < 3:
        points = [p for r in building.get('rooms', []) if r.get('level') == first.get('id') for p in r.get('polygon', [])]
        joints = {j['id']: j['at'] for j in building.get('joints', [])}
        points += [p for w in building.get('walls', []) for p in
                   ([w['from'], w['to']] if 'from' in w else [joints[j] for j in w.get('joints', []) if j in joints])]
        if points:
            lo, hi = ([fn(p[i] for p in points) for i in (0, 1)] for fn in (min, max))
            outline = [[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]
    poly = [_world(building, p) for p in outline]
    if not poly:
        return terrain.ground_at(pads, building.get('position', [0, 0])) + building['foundation'].get('offset_ft', 0)
    samples = list(poly)
    for a, b in zip(poly, poly[1:] + poly[:1]):
        count = max(1, math.ceil(math.dist(a, b)))
        samples.extend([[a[k] + (b[k]-a[k])*j/count for k in (0, 1)] for j in range(count+1)])
    # Match the local one-foot grid used by footprintGround, then include pad
    # vertices and intersections so a narrow high pad cannot fall between it.
    from services.twin_register import to_local
    local = [to_local(building, p) for p in poly]
    x, y = min(p[0] for p in local), min(p[1] for p in local)
    while x <= max(p[0] for p in local):
        yy = y
        while yy <= max(p[1] for p in local):
            if terrain.inside(local, [x, yy]):
                samples.append(_world(building, [x, yy]))
            yy += 1
        x += 1
    samples.extend(p for pad in pads for p in pad['polygon'] if terrain.inside(poly, p))
    for pad in pads:
        for a, b in zip(pad['polygon'], pad['polygon'][1:] + pad['polygon'][:1]):
            for c, d in zip(poly, poly[1:] + poly[:1]):
                v, w = [b[i]-a[i] for i in (0, 1)], [d[i]-c[i] for i in (0, 1)]
                den = v[0]*w[1]-v[1]*w[0]
                if abs(den) < 1e-10:
                    continue
                q = [c[i]-a[i] for i in (0, 1)]
                t, u = (q[0]*w[1]-q[1]*w[0])/den, (q[0]*v[1]-q[1]*v[0])/den
                if 0 <= t <= 1 and 0 <= u <= 1:
                    samples.append([a[i]+t*v[i] for i in (0, 1)])
    return max(terrain.ground_at(pads, p) for p in samples) + building['foundation'].get('offset_ft', 0)


def _anchor_geometry(value):
    # Appearance and provenance do not reshape a host.
    ignored = {'materials', 'material', 'tint', 'color', 'colour', 'name', 'label',
               'src', 'source', 'confidence', 'visible_in', 'casts_shadow', 'light_entity',
               'emissive', 'emissive_color', 'slots', 'finishes', 'faces',
               'floor_material', 'ceiling_material', 'wall_material', 'ha_area'}
    if isinstance(value, dict):
        return {k: _anchor_geometry(v) for k, v in value.items() if k not in ignored}
    if isinstance(value, list):
        return [_anchor_geometry(v) for v in value]
    if type(value) in (int, float):
        return round(value, 8)
    return value


def _anchor_frame(model, host):
    """Return geometry plus nested rigid frames in east/north/up feet."""
    kind, hid = host['kind'], host['id']
    lists = {'wall': 'walls', 'roof': 'roofs', 'room': 'rooms', 'porch': 'porches',
             'stair': 'stairs', 'opening': 'openings', 'item': 'items',
             'fixture': 'fixtures', 'light': 'lights', 'anchor': 'anchors', 'solar_zone': 'solar_zones'}
    matches = []
    for b in model.get('buildings', []):
        if host.get('building') and b['id'] != host['building']:
            continue
        if kind == 'building':
            pieces = [b] if hid in (b['id'], 'structure') else []
        elif kind == 'floor':
            pieces = [l for l in b.get('levels', []) if hid == 'floor:' + l['id'] or hid == l['id']]
        elif kind == 'roof':
            sections = b.get('roof', {}).get('sections', b.get('roofs', []))
            pieces = [p for i, p in enumerate(sections) if (p.get('id') or f'roof:{i}') == hid]
        else:
            pieces = [p for p in b.get(lists.get(kind, ''), []) if p.get('id') == hid]
            if kind == 'porch' and isinstance(b.get('porch'), dict) and hid == b['porch'].get('id', 'porch'):
                pieces.append(b['porch'])
        matches.extend((b, p) for p in pieces if p.get('state') not in ('ghost', 'proposal'))
    if len(matches) == 1:
        b, p = matches[0]
        pos = b.get('position', [0, 0])
        frames = [([*pos, _building_base(model, b)], [b.get('rotation', 0), 0, 0])]
        geometry = deepcopy(p)
        if kind == 'building':
            geometry = {k: v for k, v in geometry.items() if k not in ('position', 'rotation', 'base', 'foundation')}
            geometry['foundation'] = {k: v for k, v in b.get('foundation', {}).items() if k not in ('mode', 'offset_ft')}
        if kind in ('item', 'fixture'):
            from services.twin_model_hosts import world_point
            try:
                if kind == 'fixture' and p.get('rect'):
                    x0, y0, x1, y1 = p['rect']
                    centre = [(x0+x1)/2, (y0+y1)/2]
                    level = next(l for l in b['levels'] if l['id'] == p['level'])
                    host_floor = p.get('host', {}).get('floor')
                    room = next((r for r in b.get('rooms', []) if r.get('id') == host_floor), None)
                    if room is None and not (p.get('host') and not host_floor):
                        room = next((r for r in b.get('rooms', []) if r.get('level') == p['level']
                            and r.get('state') != 'ghost' and terrain.inside(r.get('polygon', []), centre)), None)
                    point = [*centre, level['elevation'] + (room or {}).get('floor_offset_ft', 0) + p.get('z0', 0)]
                elif 'host' in p:
                    point = world_point(b, p['host'], p.get('offset', 0))
                else:
                    point = [*p['at'][:2], p['at'][2] if len(p['at']) > 2 else 0]
            except (ValueError, KeyError, StopIteration):
                return None
            point[2] += p.get('elevation', 0)
            frames.append((point, [p.get('rotation', 0), p.get('pitch', 0), p.get('roll', 0)]))
            geometry = {k: v for k, v in geometry.items() if k not in ('host', 'at', 'rotation', 'pitch', 'roll', 'elevation', 'offset', 'z0')}
            if kind == 'fixture' and p.get('rect'):
                geometry['rect'] = [x1-x0, y1-y0]
        else:
            level = next((l for l in b.get('levels', []) if l['id'] == p.get('level')), None)
            geometry = [geometry, {k: level.get(k) for k in ('elevation', 'ceiling')} if level else None]
            # Connected walls store joint ids; changing a joint reshapes the mesh.
            if kind in ('wall', 'opening'):
                wall = p if kind == 'wall' else next((w for w in b.get('walls', []) if w['id'] == p.get('wall')), {})
                geometry.extend([wall, [j for j in b.get('joints', []) if j['id'] in wall.get('joints', [])], b.get('roof', b.get('roofs', []))])
                geometry.extend([[o for o in b.get('openings', []) if o.get('wall') == wall.get('id')],
                                 [r for r in b.get('rooms', []) if r.get('level') == wall.get('level')]])
        return _anchor_geometry(geometry), frames
    if matches or host.get('building'):
        return None
    site = model.get('site', {})
    name = {'terrace': 'terraces', 'retaining_wall': 'terraces', 'hardscape': 'hardscape', 'fence': 'fence'}.get(kind)
    pool = site.get('pool') or {}
    if kind == 'pool':
        pieces = [pool] if hid == pool.get('id', 'pool:0') else []
    elif kind in ('spa', 'ledge', 'steps'):
        pieces = [p for p in pool.get('features', []) if p.get('id') == hid and p.get('kind') == kind]
    else:
        pieces = [p for p in _pieces(site.get(name)) if p.get('id') == hid]
    if len(pieces) != 1:
        return None
    p = pieces[0]
    key = next((k for k in ('polygon', 'points', 'polyline') if p.get(k)), None)
    if key is None:
        return None
    points, pads = p[key], site.get('terraces', [])
    origin = points[0]
    height = p.get('elevation') if p.get('elevation') is not None else terrain.ground_at(pads, origin)
    if kind in ('terrace', 'retaining_wall'):
        height = p.get('height', 0)
    if kind in ('pool', 'spa', 'ledge', 'steps'):
        if not pool.get('polygon'):
            return None
        height = terrain.ground_at(pads, pool['polygon'][0]) + (pool.get('elevation') or 0)
        if kind == 'spa':
            raise_in = p.get('raise_in')
            height += .45 + (((12 if raise_in is None else raise_in) / 12) if (p.get('mode') or 'raised') == 'raised' else 0)
    geometry = {**p, key: [[q[i]-origin[i] for i in (0, 1)] for q in points]}
    # Relative ground profiles distinguish a rigid translation from a pad step
    # bending a fence/hardscape after it moves.
    if kind in ('hardscape', 'fence') and p.get('elevation') is None:
        geometry['_ground'] = [terrain.ground_at(pads, q)-height for q in points]
    if kind in ('pool', 'spa', 'ledge', 'steps'):
        pool_origin = pool['polygon'][0]
        relative = lambda ps: [[q[i]-pool_origin[i] for i in (0, 1)] for q in ps]
        # Pool depth sets feature slab bottoms; siblings cut their surfaces.
        # Normalize against the pool so translating the whole group is rigid.
        siblings = [{**f, 'polygon': relative(f.get('polygon', []))} for f in pool.get('features', [])
                    if kind == 'pool' or f.get('id') != hid]
        if kind == 'pool':
            geometry['features'] = siblings
        else:
            geometry['_pool'] = {**pool, 'polygon': relative(pool['polygon']), 'features': siblings}
    return _anchor_geometry(geometry), [([*origin, height], [0, 0, 0])]


def _anchor_rotate(point, angles, inverse=False):
    # THREE's YXZ object rotation, converted from [east, up, -north].
    def yaw(p, a):
        c, s = math.cos(a), math.sin(a)
        return [p[0]*c-p[1]*s, p[0]*s+p[1]*c, p[2]]

    def pitch(p, a):
        c, s = math.cos(a), math.sin(a)
        return [p[0], p[1]*c-p[2]*s, p[2]*c+p[1]*s]

    def roll(p, a):
        c, s = math.cos(a), math.sin(a)
        return [p[0]*c-p[2]*s, p[1], p[0]*s+p[2]*c]

    turns = [(yaw, angles[0]), (pitch, angles[1]), (roll, angles[2])]
    for rotate, angle in turns if inverse else reversed(turns):
        point = rotate(point, math.radians(-angle if inverse else angle))
    return point


def _anchor_transform(point, frames, inverse=False):
    for origin, angles in frames if inverse else reversed(frames):
        point = (_anchor_rotate([point[i]-origin[i] for i in range(3)], angles, True) if inverse
                 else [v+origin[i] for i, v in enumerate(_anchor_rotate(point, angles))])
    return point


def _anchor_reference(model, fixture, point):
    try:
        reference = _reference(model, fixture, point)
    except ValueError:
        # The client resolves a missing floor at datum zero, retaining the
        # authored reference so restoring the floor can repair the orphan.
        return 0
    if fixture['ref'] == 'floor':
        building = next(b for b in model['buildings'] if b['id'] == fixture['building'])
        reference += _building_base(model, building) - building.get('base', 0)
    return reference


def _follow_anchors(before, after, fixture, cache):
    for i, anchor in enumerate(fixture.get('anchors', [])):
        if anchor is None:
            continue
        host = anchor['host']
        key = json.dumps(host, sort_keys=True)
        if key not in cache:
            cache[key] = _anchor_frame(before, host), _anchor_frame(after, host)
        old, new = cache[key]
        if old is None or new is None or old[0] != new[0]:
            fixture['anchors'][i] = None
            # A ground/floor reference can move even when its host is removed
            # or reshaped. Preserve the last absolute position on detachment.
            point = fixture['path'][i]
            try:
                height = point[2] + _anchor_reference(before, fixture, point)
                fixture['path'][i] = [*point[:2], height - _anchor_reference(after, fixture, point)]
            except (ValueError, StopIteration):
                pass
            continue
        if old[1] == new[1]:
            continue
        point = fixture['path'][i]
        try:
            point = _anchor_transform(anchor['local'], new[1])
            new_ref = _anchor_reference(after, fixture, point)
        except (ValueError, StopIteration):
            fixture['anchors'][i] = None
            continue
        fixture['path'][i] = [*point[:2], point[2]-new_ref]


def follow_host_moves(before, after):
    """Carry endpoint references through rigid host moves before re-resolution.

    Match the old endpoints first. Only a verified whole-host translation or
    the building's explicit frame transform can carry a snap beyond 0.5 ft.
    A reshape/split cannot silently retarget a run to the edge at its old index.
    """
    rows_by_owner = list(after.get('light_fixtures', {}).values())
    rows_by_owner.append(after.get('effect_fixtures', []))
    anchor_frames = {}
    for rows in rows_by_owner:
        for f in rows:
            _follow_anchors(before, after, f, anchor_frames)
            snap = f.get('snap')
            if not snap or f.get('detached'):
                continue
            old = _host_edges(before, snap['host'])
            new = _host_edges(after, snap['host'])
            if not old or not new or _match(old, snap) is None:
                continue
            transform = None
            if snap['host']['kind'] in ('wall', 'step'):
                collection = 'walls' if snap['host']['kind'] == 'wall' else 'stairs'
                b = next((b for b in before['buildings'] if any(p['id'] == snap['host']['id'] for p in b.get(collection, []))), None)
                a = next((a for a in after['buildings'] if b and a['id'] == b['id']), None)
                if a and any(a.get(k, 0) != b.get(k, 0) for k in ('position', 'rotation')):
                    from services.twin_register import to_local
                    transform = lambda p: _world(a, to_local(b, p))
            if transform is None:
                # Compare whole sets, independent of winding, edge order and ids.
                old_points = {tuple(p[:2]) for e in old for p in e}
                new_points = {tuple(p[:2]) for e in new for p in e}
                if len(old_points) != len(new_points):
                    continue
                delta = [sum(p[i] for p in new_points)/len(new_points) - sum(p[i] for p in old_points)/len(old_points) for i in (0, 1)]
                if max(abs(v) for v in delta) < 1e-9:
                    continue
                if any(not any(math.dist([p[i]+delta[i] for i in (0, 1)], q) < 1e-6 for q in new_points) for p in old_points):
                    continue
                transform = lambda p: [p[i]+delta[i] for i in (0, 1)]
            candidate = deepcopy(snap)
            candidate['edge'] = {k: transform(p) for k, p in snap['edge'].items()}
            if _match(new, candidate) is not None:
                snap['edge'] = candidate['edge']
