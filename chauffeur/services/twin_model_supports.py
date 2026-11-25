"""Optional roof support records; no geometry generation or save migration."""
from copy import deepcopy
import math
import re

SUPPORT_KINDS = ['walls', 'bracket', 'corbel', 'brace', 'cable', 'post']
ROOF_FIELDS = ('support', 'host', 'thickness_ft', 'fascia', 'gable_beam', 'roof_frame', 'ends', 'underside', 'wall_attachments')
CHOICE_FIELDS = (*ROOF_FIELDS, 'edges')
_SIZES = dict(bracket=.3, corbel=.5, brace=.3, cable=.08, post=.5)
_EPS = 1e-8
SUPPORT_STYLES = {'bracket': ('plain',), 'corbel': ('scroll', 'plain'), 'brace': ('plain', 'arched'), 'cable': (), 'post': ()}


def allowed_end_indices(roof):
    edges = roof.get('edges')
    ends = roof.get('ends') if isinstance(roof.get('ends'), dict) else {}
    host = roof.get('host') if isinstance(roof.get('host'), dict) else {}
    if not isinstance(edges, list):
        # Flat sections may omit their redundant edge list.
        kind = roof.get('kind')
        sides = ('y0', 'x1', 'y1', 'x0')
        edges = [dict(setting=('sloped' if kind == 'flat' or kind == 'shed' and side == roof.get('low_side')
                    or kind in ('gable', 'hip') and side[0] != roof.get('ridge') else
                    ends.get(side, 'gable')), pitch=roof.get('pitch', 0)) for side in sides]
    # Decision: a flat awning allows closed ends on every non-host edge.
    return {str(i) for i, e in enumerate(edges) if isinstance(e, dict) and i != host.get('edge')
            and (e.get('setting') in ('gable', 'clip') or e.get('pitch', roof.get('pitch', 0)) == 0)}


def normalize_box(roof, notes):
    legacy = {k:v for k,v in roof.get('ends', {}).items() if k in ('x0','x1','y0','y1')} if isinstance(roof.get('ends'), dict) and 'rect' in roof else {}
    if not is_supported(roof):
        roof.pop('underside', None)
        if legacy: roof['ends'] = legacy
        else: roof.pop('ends', None)
        roof.pop('wall_attachments', None)
        return
    if 'ends' in roof:
        ends = roof['ends']; allowed = allowed_end_indices(roof)
        clean = {k:v for k,v in ends.items() if k in allowed and v == 'closed'} if isinstance(ends, dict) else {}
        if not isinstance(ends, dict) or any(k not in legacy and k not in clean for k in ends): _note(roof, notes)
        if clean or legacy: roof['ends'] = {**legacy, **clean}
        else: roof.pop('ends', None)
    if 'wall_attachments' in roof:
        saved = roof['wall_attachments']
        if not isinstance(saved, dict):
            roof.pop('wall_attachments'); _note(roof, notes)
        else:
            roof['wall_attachments'] = {str(i): {k:v for k,v in saved.get(str(i), {}).items()
                if k == 'wall' and isinstance(v, str) or k == 'wall_offset' and _number(v)}
                if isinstance(saved.get(str(i)), dict) else {} for i in range(len(roof.get('edges') or area_of(roof)))}
    if 'underside' in roof:
        value = roof['underside']
        if isinstance(value, dict) and value.get('kind') == 'flat':
            drop = value.get('drop_ft', 0)
            if not _number(drop, 0, 3): drop = 0; _note(roof, notes)
            roof['underside'] = dict(kind='flat', drop_ft=drop)
        else:
            roof.pop('underside', None)
            if not isinstance(value, dict) or value.get('kind') != 'exposed': _note(roof, notes)


def is_supported(roof):
    support = roof.get('support')
    return isinstance(support, dict) and bool(support.get('kind')) and support['kind'] != 'walls'


def _number(value, lo=None, hi=None):
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and (lo is None or value >= lo) and (hi is None or value <= hi))
    except OverflowError:
        return False


def _point(value):
    return isinstance(value, (list, tuple)) and len(value) == 2 and all(_number(v) for v in value)


def host_candidates(roof, building):
    """Facing, overlapping wall/edge pairs, nearest first (one per wall)."""
    area = area_of(roof)
    sign = 1 if sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(area, area[1:]+area[:1])) > 0 else -1
    points = {j['id']: j['at'] for j in building.get('joints', [])}
    result = []
    for wall in building.get('walls', []):
        if wall.get('level') != roof.get('level') or wall.get('state') == 'ghost' or wall.get('kind') == 'separator' or not wall.get('exterior', True):
            continue
        a, b = (wall['from'], wall['to']) if 'from' in wall else [points[j] for j in wall['joints']]
        length = math.dist(a, b)
        if length <= _EPS:
            continue
        tangent = [(b[k]-a[k])/length for k in (0, 1)]
        pairs = []
        for i, p in enumerate(area):
            q = area[(i+1) % len(area)]
            if wall_axis(a, b) != _axis(p, q):
                continue
            p, q = frame_point(roof, p), frame_point(roof, q)
            span = math.dist(p, q)
            if span <= _EPS:
                continue
            u = [(q[k]-p[k])/span for k in (0, 1)]
            if abs(u[0]*tangent[0]+u[1]*tangent[1]) < math.cos(math.radians(1))-_EPS:
                continue
            normal = [sign*u[1], -sign*u[0]]
            distances = [sum((v[k]-p[k])*normal[k] for k in (0, 1)) for v in (a, b)]
            along = [sum((v[k]-p[k])*u[k] for k in (0, 1)) for v in (a, b)]
            if max(distances) < -_EPS or min(span, max(along))-max(0, min(along)) <= _EPS:
                continue
            pairs.append((abs(sum(distances)/2), i))
        if pairs:
            distance, edge = min(pairs)
            result.append((distance, wall['id'], edge))
    return sorted(result)


def validate_edit(roof, building, edit, refused):
    """Reject bad user/agent input before normalization can discard intent."""
    support = edit.get('support', {})
    if not isinstance(support, dict):
        raise refused('Choose roof support settings.')
    if 'support' in edit and not is_supported(roof) and 'kind' not in support:
        raise refused('Choose a support kind first.')
    kind = support.get('kind', roof.get('support', {}).get('kind', 'walls'))
    if not isinstance(kind, str) or kind not in SUPPORT_KINDS:
        raise refused('Choose Walls, Straight brackets, Corbels, Braces, Cables or Posts.')
    if 'count' in support and (type(support['count']) not in (int, float) or not _number(support['count'], 0, 40) or support['count'] != int(support['count'])):
        raise refused('Support count must be a whole number from 0 to 40.')
    for key, lo, hi in [('inset_ft', 0, 6), ('size_ft', .05, 3), ('spacing_ft', 1, 20)]:
        if key in support and not _number(support[key], lo, hi):
            raise refused(f'Choose {key.replace("_ft", "").replace("_", " ")} from {lo} to {hi} ft.')
    if 'style' in support and (not isinstance(support['style'], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', support['style'])):
        raise refused('Use a support style of 1 to 64 letters, numbers, hyphens or underscores.')
    if 'style' in support and support['style'] not in SUPPORT_STYLES.get(kind, ()):
        raise refused('Choose a built-in style for this support kind.')
    if any(k in edit for k in ('ends', 'underside')) and kind == 'walls':
        raise refused('Choose supports before adding ends or a ceiling underneath.')
    if 'ends' in edit:
        probe = {**roof, **{k:edit[k] for k in ('host',) if isinstance(edit.get(k), dict)}}
        if edit.get('host', 1) is None: probe.pop('host', None)
        allowed = allowed_end_indices(probe)
        if not isinstance(edit['ends'], dict) or any(k not in allowed or v not in ('open','closed') for k,v in edit['ends'].items()):
            raise refused('Choose Open or Closed on an end edge, away from the host wall and sloped eaves.')
    if 'underside' in edit:
        value = edit['underside']
        if (not isinstance(value, dict) or value.get('kind') not in ('flat','exposed')
                or any(k not in ('kind','drop_ft') for k in value)
                or 'drop_ft' in value and (value['kind'] != 'flat' or not _number(value['drop_ft'], 0, 3))):
            raise refused('Choose None or Flat underneath, with a drop from 0 to 3 ft.')
    if 'thickness_ft' in edit and not _number(edit['thickness_ft'], .05, 2):
        raise refused('Choose thickness from 0.05 to 2 ft.')
    if 'fascia' in edit and type(edit['fascia']) is not bool:
        raise refused('Choose whether to show fascia.')
    if 'roof_frame' in edit:
        frame = edit['roof_frame']
        if not isinstance(frame, dict) or not _point(frame.get('origin')) or not _number(frame.get('angle')):
            raise refused('Choose a finite roof origin and angle.')
    count = support.get('count', roof.get('support', {}).get('count', 2))
    for at in [source['at'] for source in (edit, support) if 'at' in source]:
        if kind == 'walls' or not isinstance(at, dict) or any(k not in {str(i) for i in range(int(count))} or not _point(v) for k, v in at.items()):
            raise refused('Choose finite positions for existing support points.')
    if 'at' in edit and edit['at'] is None:
        raise refused('Choose support positions or reset with an empty map.')
    if 'host' in edit:
        if kind == 'walls':
            raise refused('Choose supports before choosing a host wall.')
        host = edit['host']
        probe = {**roof, **{k: edit[k] for k in ('roof_frame',) if k in edit}}
        if host is not None and (not isinstance(host, dict) or type(host.get('edge')) is not int or
                not any(w == host.get('wall') and e == host['edge'] for _, w, e in host_candidates(probe, building))):
            raise refused('Choose a facing, parallel wall on the same floor.')


def _note(roof, notes):
    label = (f"Roof {roof['name']}" if roof.get('name') else
             'Awning' if is_supported(roof) else f"Roof {roof.get('id', 'unnamed')}")
    text = f"{label}: reset invalid awning settings to their defaults."
    if text not in notes:
        notes.append(text)


def area_of(roof):
    if 'area' in roof:
        return roof['area']
    x0, y0, x1, y1 = roof['rect']
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def normalize_support(roof, notes):
    """Normalize only opted-in fields in place, with one named correction note."""
    if 'support' in roof:
        support = roof['support']
        if not isinstance(support, dict) or not isinstance(support.get('kind'), str) or support['kind'] not in SUPPORT_KINDS:
            roof.pop('support'); _note(roof, notes)
        elif support['kind'] == 'walls':
            roof.pop('support')
        else:
            kind = support['kind']
            clean = {'kind': kind}
            for key, default, valid in (
                ('count', 2, lambda v: type(v) is int and 0 <= v <= 40),
                ('inset_ft', .6, lambda v: _number(v, 0, 6)),
                ('size_ft', _SIZES[kind], lambda v: _number(v, .05, 3)),
            ):
                value = support.get(key, default)
                if not valid(value):
                    value = default; _note(roof, notes)
                clean[key] = value
            for key, valid in (
                ('spacing_ft', lambda v: _number(v, 1, 20)),
                ('style', lambda v: isinstance(v, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', v)),
            ):
                if key in support:
                    if valid(support[key]):
                        clean[key] = support[key]
                    else:
                        _note(roof, notes)
            if 'at' in support:
                at = support['at']
                if isinstance(at, dict):
                    allowed = {str(i) for i in range(clean['count'])}
                    overrides = {k: list(v) for k, v in at.items() if k in allowed and _point(v)}
                    if overrides:
                        clean['at'] = overrides
                    if len(overrides) != len(at):
                        _note(roof, notes)
                else:
                    _note(roof, notes)
            roof['support'] = clean
    if 'thickness_ft' in roof and not _number(roof['thickness_ft'], .05, 2):
        roof['thickness_ft'] = .3; _note(roof, notes)
    if 'fascia' in roof and type(roof['fascia']) is not bool:
        roof['fascia'] = True; _note(roof, notes)
    if 'gable_beam' in roof and type(roof['gable_beam']) is not bool:
        roof.pop('gable_beam'); _note(roof, notes)
    if 'roof_frame' in roof:
        frame = roof['roof_frame']
        if not isinstance(frame, dict) or not _point(frame.get('origin')) or not _number(frame.get('angle')):
            roof.pop('roof_frame'); _note(roof, notes)
        else:
            roof['roof_frame'] = dict(origin=list(frame['origin']), angle=frame['angle'])
    for edge in roof.get('edges', []) if isinstance(roof.get('edges'), list) else []:
        if isinstance(edge, dict) and 'overhang_ft' in edge and not _number(edge['overhang_ft'], 0, 6):
            uniform = roof.get('overhang', 1)
            edge['overhang_ft'] = uniform if _number(uniform, 0, 6) else 1
            _note(roof, notes)
    normalize_box(roof, notes)
    return roof


def _axis(a, b):
    return 0 if abs(a[0]-b[0]) <= _EPS else 1 if abs(a[1]-b[1]) <= _EPS else None


def wall_axis(a, b):
    """Constant coordinate of a wall within one degree of a building axis."""
    dx, dy = abs(b[0]-a[0]), abs(b[1]-a[1])
    return (0 if dx <= dy*math.tan(math.radians(1))+_EPS else
            1 if dy <= dx*math.tan(math.radians(1))+_EPS else None)


def frame_point(roof, point, *, inverse=False):
    frame = roof.get('roof_frame')
    if not frame:
        return list(point)
    angle = frame['angle'] * (-1 if inverse else 1)
    c, s = math.cos(angle), math.sin(angle)
    x, y = [point[i]-frame['origin'][i] for i in (0, 1)]
    return [frame['origin'][0]+c*x-s*y, frame['origin'][1]+s*x+c*y]


def normalize_host(roof, building, notes):
    """Resolve the optional roof host against actual wall geometry; keep or flag."""
    if 'host' not in roof:
        return
    host = roof['host']
    area = area_of(roof)
    wall = next((w for w in building.get('walls', []) if isinstance(host, dict) and w['id'] == host.get('wall')), None)
    edge = host.get('edge') if isinstance(host, dict) else None
    a = b = None
    valid = isinstance(host, dict) and isinstance(host.get('wall'), str) and type(edge) is int and 0 <= edge < len(area)
    if valid and wall is not None:
        points = {j['id']: j['at'] for j in building.get('joints', [])}
        endpoints = [points.get(j) for j in wall.get('joints', [])]
        a, b = (wall['from'], wall['to']) if 'from' in wall and 'to' in wall else (endpoints if len(endpoints) == 2 else (None, None))
        axis = _axis(area[edge], area[(edge+1) % len(area)])
        valid = (wall.get('level') == roof.get('level') and a is not None and b is not None
                 and axis is not None and wall_axis(a, b) == axis)
        if valid:
            roof['host'] = {'wall': wall['id'], 'edge': edge}
            building['flags'] = [f for f in building.get('flags', []) if not
                (f.get('id') == roof['id'] and f.get('kind') == 'roof' and
                 any(t in f.get('text', '') for t in ('supporting wall', 'one degree', 'diagonal wall', 'host wall')))]
            if isinstance(roof.get('edges'), list) and edge < len(roof['edges']):
                record = roof['edges'][edge]
                same_wall = record.get('wall') == wall['id']
                record['wall'] = wall['id']
                defaults = {'wall_offset': area[edge][axis] - a[axis]}
                if is_supported(roof):
                    defaults['wall_along_offset'] = area[edge][1-axis] - a[1-axis]
                for key, default in defaults.items():
                    if key in record and not _number(record[key]):
                        record[key] = default
                        _note(roof, notes)
                    elif not same_wall or key not in record:
                        record[key] = default
            return
    roof.pop('host', None)
    angle_detach = (wall is not None and is_supported(roof) and a is not None and b is not None and wall_axis(a, b) is None)
    if not angle_detach and not (valid and wall is None):
        _note(roof, notes)
    if valid and wall is None or (wall is not None and is_supported(roof)
            and wall.get('level') == roof.get('level') and a is not None and b is not None
            and wall_axis(a, b) is None):
        label = (f"Roof {roof['name']}" if roof.get('name') else
                 'Awning' if is_supported(roof) else f"Roof {roof['id']}")
        text = (f"{label} has lost its supporting wall." if wall is None else
                f"{label} stays in place; its wall is more than one degree from a building axis. Place it again to attach it.")
        if text not in notes:
            notes.append(text)
        flags = building.setdefault('flags', [])
        flags[:] = [f for f in flags if not (f.get('id') == roof['id'] and f.get('kind') == 'roof'
                    and any(t in f.get('text', '') for t in ('supporting wall', 'one degree', 'diagonal wall', 'host wall')))]
        if not any(f.get('id') == roof['id'] and f.get('text') == text for f in flags):
            flags.append({'id': roof['id'], 'kind': 'roof', 'text': text,
                          'at': frame_point(roof, [sum(p[i] for p in area)/len(area) for i in (0, 1)]),
                          'level': roof.get('level')})


def _edge_rows(roof):
    area = area_of(roof)
    segments = list(zip(area, area[1:] + area[:1]))
    sign = 1 if sum(p[0]*q[1]-p[1]*q[0] for p, q in segments) > 0 else -1
    rows = []
    for a, b in segments:
        axis = _axis(a, b)
        if axis is None:
            raise ValueError('Roof areas must have square corners.')
        outward = sign*(b[1]-a[1]) if axis == 0 else -sign*(b[0]-a[0])
        rows.append((axis, outward, a[axis], min(a[1-axis], b[1-axis]), max(a[1-axis], b[1-axis])))
    return rows


def _matching_edge(row, candidates):
    axis, outward, line, lo, hi = row
    matches = [(i, other) for i, other in enumerate(candidates)
               if other[0] == axis and other[1]*outward > 0]
    return min(matches, key=lambda pair: (abs(pair[1][2]-line),
        -max(0, min(hi, pair[1][4])-max(lo, pair[1][3])), pair[0]))[0] if matches else None


def edge_pairs(source, target):
    """Target/source indices for optional data; legacy roofs keep zip ordering."""
    if not any(k in source for k in ROOF_FIELDS) and not any('overhang_ft' in e for e in source.get('edges', [])):
        return list(zip(range(len(target.get('edges', []))), range(len(source.get('edges', [])))))
    old = _edge_rows(source)
    return [(i, index) for i, row in enumerate(_edge_rows(target))
            if (index := _matching_edge(row, old)) is not None]


def carry_fields(source, target, *, overwrite=False):
    """Keep person-set record fields across a geometry replacement."""
    for key in ROOF_FIELDS:
        if key in ('ends', 'wall_attachments'):
            continue
        if key in source and (overwrite or key not in target):
            target[key] = deepcopy(source[key])
            if key == 'host' and isinstance(target[key], dict):
                index = source[key].get('edge')
                old = _edge_rows(source)
                if type(index) is int and 0 <= index < len(old):
                    mapped = _matching_edge(old[index], _edge_rows(target))
                    if mapped is not None:
                        target[key]['edge'] = mapped
    if 'edges' not in target and any('overhang_ft' in e for e in source.get('edges', [])):
        target['edges'] = deepcopy(source['edges'])
    for target_index, source_index in edge_pairs(source, target):
        if source_index >= len(source.get('edges', [])) or target_index >= len(target.get('edges', [])):
            continue
        old, new = source['edges'][source_index], target['edges'][target_index]
        if 'overhang_ft' in old and (overwrite or 'overhang_ft' not in new):
            new['overhang_ft'] = deepcopy(old['overhang_ft'])
    if 'ends' in source and (overwrite or not any(str(k).isdigit() for k in target.get('ends', {}))):
        # Closed ends belong to a whole edge: a split/deleted edge loses its own entry.
        old_segments = list(zip(area_of(source), area_of(source)[1:]+area_of(source)[:1]))
        new_segments = list(zip(area_of(target), area_of(target)[1:]+area_of(target)[:1]))
        clean = {k:v for k,v in target.get('ends', {}).items() if not str(k).isdigit()}
        for ti, si in edge_pairs(source, target):
            if str(si) in source['ends'] and (len(old_segments) == len(new_segments) or set(map(tuple,old_segments[si])) == set(map(tuple,new_segments[ti]))):
                clean[str(ti)] = source['ends'][str(si)]
        if clean: target['ends'] = clean
        else: target.pop('ends', None)
    if 'wall_attachments' in source and (overwrite or 'wall_attachments' not in target):
        target['wall_attachments'] = {str(ti):deepcopy(source['wall_attachments'].get(str(si), {}))
                                      for ti,si in edge_pairs(source, target)}
    return target


def support_points(roof):
    """Authored outer-edge points, in edge order; u is distance in feet."""
    if not is_supported(roof) or roof['support'].get('count', 2) == 0:
        return []
    area = area_of(roof)
    segments = list(zip(area, area[1:] + area[:1]))
    host = roof.get('host', {}).get('edge')
    if type(host) is int and 0 <= host < len(area):
        a, b = segments[host]
        dx, dy = b[0]-a[0], b[1]-a[1]
        orientation = sum(p[0]*q[1]-p[1]*q[0] for p, q in segments)
        sign = 1 if orientation > 0 else -1
        inward = [-dy*sign, dx*sign]
        candidates = [(i, (p[0]-a[0])*inward[0] + (p[1]-a[1])*inward[1])
                      for i, (p, q) in enumerate(segments) if i != host
                      and _axis(p, q) == _axis(a, b) and (q[0]-p[0])*dx+(q[1]-p[1])*dy < 0]
        edge = min(candidates, key=lambda v: (-v[1], v[0]))[0] if candidates else host
    else:
        from services.twin_model_roofs import eave_edge_indices
        edge = min(eave_edge_indices(roof), default=0)
    a, b = segments[edge]
    width = math.dist(a, b)
    support = roof['support']; count = support.get('count', 2)
    inset = min(support.get('inset_ft', .6), width/2)
    result = []
    for i in range(count):
        u = inset + i*(width-2*inset)/max(1, count-1)
        at = support.get('at', {}).get(str(i))
        if at is None:
            at = frame_point(roof, [a[k]+(b[k]-a[k])*u/width for k in (0, 1)])
        else:
            at = list(at)
            local = frame_point(roof, at, inverse=True)
            u = sum((local[k]-a[k])*(b[k]-a[k])/width for k in (0, 1))
        result.append({'id': f'support:{i}', 'edge': edge, 'u': u, 'at': at})
    return result
