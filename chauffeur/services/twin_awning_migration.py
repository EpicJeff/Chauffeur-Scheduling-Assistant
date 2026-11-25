"""Turn legacy roof attachments into ordinary roof records, without I/O."""
from copy import deepcopy
import math
import json

_EPS = 1e-6
_KINDS = ('awning', 'shed_continuation')
_SIDES = ('y0', 'x1', 'y1', 'x0')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _inside(point, polygon):
    x, y = point
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > y) != (b[1] > y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:
            inside = not inside
    return inside


def _lines(building):
    joints = {j.get('id'): j.get('at') for j in building.get('joints', []) if isinstance(j, dict)}
    result = []
    for wall in building.get('walls', []):
        if not isinstance(wall, dict):
            continue
        points = [wall.get('from'), wall.get('to')]
        if not all(isinstance(p, (list, tuple)) and len(p) == 2 for p in points):
            points = [joints.get(j) for j in wall.get('joints', [])]
        if (len(points) == 2 and all(isinstance(p, (list, tuple)) and len(p) == 2
                and all(_number(v) for v in p) for p in points) and math.dist(*points) > _EPS):
            result.append(dict(wall, **{'from': points[0], 'to': points[1]}))
    return result


def _host(awning, section, walls):
    exterior = [w for w in walls if w.get('exterior')]
    if awning.get('wall'):
        return next((w for w in exterior if w.get('id') == awning['wall']), None)
    y0 = section['rect'][1]
    best, overlap = None, 0
    for wall in exterior:
        a, b = wall['from'], wall['to']
        if abs(a[1]-y0) > 1e-4 or abs(b[1]-y0) > 1e-4:
            continue
        covered = min(awning['x1'], max(a[0], b[0])) - max(awning['x0'], min(a[0], b[0]))
        if covered > overlap:
            best, overlap = wall, covered
    if best is not None:
        return best
    midpoint = [(awning['x0']+awning['x1'])/2, y0]
    nearest = 2 + _EPS
    for wall in exterior:
        a, b = wall['from'], wall['to']
        delta = [b[i]-a[i] for i in (0, 1)]
        t = max(0, min(1, sum((midpoint[i]-a[i])*delta[i] for i in (0, 1))
                       / sum(v*v for v in delta)))
        distance = math.dist(midpoint, [a[i]+t*delta[i] for i in (0, 1)])
        if distance < nearest:
            best, nearest = wall, distance
    return best


def _normal(building, wall, walls):
    a, b = wall['from'], wall['to']
    length = math.dist(a, b); dx, dy = [(b[i]-a[i])/length for i in (0, 1)]
    level = next((l for l in building.get('levels', []) if l.get('id') == wall.get('level')), {})
    outlines = [level['outline']] if len(level.get('outline', [])) >= 3 else []
    if not outlines:
        # Same boundary walk the renderer uses when no cached floor outline exists.
        remaining = [[w['from'], w['to']] for w in walls if w.get('level') == wall.get('level')
                     and w.get('exterior') and w.get('kind') != 'separator']
        while remaining:
            chain = remaining.pop(0)
            while math.dist(chain[0], chain[-1]) >= .001:
                index = next((i for i, (p, q) in enumerate(remaining)
                              if min(math.dist(p, chain[-1]), math.dist(q, chain[-1])) < .001), None)
                if index is None:
                    break
                p, q = remaining.pop(index)
                chain.append(q if math.dist(p, chain[-1]) < .001 else p)
            if len(chain) > 3 and math.dist(chain[0], chain[-1]) < .001:
                outlines.append(chain[:-1])
    midpoint = [(a[i]+b[i])/2 for i in (0, 1)]
    if outlines:
        sign = -1 if any(_inside([midpoint[0]+dy*.1, midpoint[1]-dx*.1], p) for p in outlines) else 1
    else:
        center = [sum(w['from'][i] for w in walls)/len(walls) for i in (0, 1)]
        value = dy*(midpoint[0]-center[0])-dx*(midpoint[1]-center[1])
        sign = -1 if value < 0 else 1
    return [sign*dy, -sign*dx]


def _flag(building, record, notes, reason='has no supporting wall; the awning was kept'):
    name = record.get('name') or 'Awning'
    text = f'{name} {reason}.'
    area = record['area']
    from services.twin_model_supports import frame_point
    flags = building.setdefault('flags', [])
    if not any(f.get('id') == record['id'] and f.get('kind') == 'roof' for f in flags):
        flags.append(dict(id=record['id'], kind='roof', text=text,
                          at=frame_point(record, [sum(p[i] for p in area)/len(area) for i in (0, 1)]),
                          level=record.get('level')))
    notes.append(text)


def _roof_material(model, building):
    result = {}
    sources = [value.get('roof') if isinstance(value, dict) else None
               for value in (building.get('materials'), model.get('materials'))]
    for value in (*sources, {'id': 'roof'}):
        if not isinstance(value, dict):
            continue
        for key in ('color', 'uv'):
            if key not in result and key in value:
                result[key] = deepcopy(value[key])
        if value.get('id'):
            return dict(id=value['id'], **result)


def _level(building, eave, wall):
    levels = building.get('levels', [])
    if wall and wall.get('level'):
        level = next((l for l in levels if l.get('id') == wall['level']), None)
        if level and level.get('elevation', 0) <= eave < level.get('elevation', 0)+wall.get('height', level.get('ceiling', 10)):
            return wall['level']
    candidates = [l for l in levels if l.get('elevation', 0) <= eave]
    return max(candidates or levels, key=lambda l: l.get('elevation', 0)).get('id') if levels else None


def _awning(model, building, awning, parent, walls, pid, notes):
    from services.twin_plan import _gutter_flag
    checked = dict(awning, id=awning.get('name') or 'Awning')
    _gutter_flag(checked, notes)
    awning = deepcopy(awning)
    for key in ('gutter', 'gutter_ack'):
        if key in checked:
            awning[key] = checked[key]
        else:
            awning.pop(key, None)
    malformed = (not all(_number(awning.get(k)) for k in ('x0', 'x1', 'depth', 'pitch', 'eave'))
                 or awning.get('x0', 0) >= awning.get('x1', 0) or awning.get('depth', 0) <= 0)
    if malformed:
        awning = deepcopy(awning)
        for key, default in (('x0', 0), ('x1', 1), ('depth', 1), ('pitch', 3), ('eave', 8)):
            if not _number(awning.get(key)):
                awning[key] = default
        if awning['x1'] <= awning['x0']:
            awning['x1'] = awning['x0']+1
        if awning['depth'] <= 0:
            awning['depth'] = 1
    wall = _host(awning, parent, walls)
    n = _normal(building, wall, walls) if wall else [0, -1]
    tangent = [-n[1], n[0]]
    axis = 0 if abs(tangent[0]) >= abs(tangent[1]) else 1
    span_mid = (awning['x0']+awning['x1'])/2
    origin = [span_mid, parent['rect'][1]]
    if wall:
        fraction = (span_mid-wall['from'][axis])/(wall['to'][axis]-wall['from'][axis])
        origin = [wall['from'][i]+fraction*(wall['to'][i]-wall['from'][i]) for i in (0, 1)]
    width = (awning['x1']-awning['x0'])/abs(tangent[axis])
    line = origin[1-axis]
    sign = 1 if n[1-axis] > 0 else -1
    lo, hi = sorted((line, line + sign*awning['depth']))
    rect = [span_mid-width/2, lo, span_mid+width/2, hi] if axis == 0 else [lo, span_mid-width/2, hi, span_mid+width/2]
    low = ('y' if axis == 0 else 'x') + ('1' if sign > 0 else '0')
    host_edge = (_SIDES.index(low)+2) % 4
    excluded = {'kind', 'section', 'wall', 'x0', 'x1', 'depth', 'eave', 'brackets',
                'gutter', 'gutter_ack', 'downspouts', 'pitch'}
    record = {k: deepcopy(v) for k, v in awning.items() if k not in excluded}
    count = awning.get('brackets', 0)
    count = math.ceil(count) if isinstance(count, (int, float)) and math.isfinite(count) else 0
    capped = min(40, max(0, count))
    if capped != count:
        notes.append(f"{awning.get('name') or 'Awning'}: limited support count to {capped} (allowed 0 to 40).")
    record.update(id=pid, area=[[rect[0], rect[1]], [rect[2], rect[1]],
                               [rect[2], rect[3]], [rect[0], rect[3]]],
                  kind='shed', low_side=low, pitch=awning['pitch'], plate=awning['eave'], overhang=0,
                  pitch_source=awning.get('pitch_source', 'default'),
                  thickness_ft=.3, fascia=False,
                  support=dict(kind='bracket', count=capped, inset_ft=.6, size_ft=.3),
                  edges=[dict(setting='sloped' if side == low else 'gable', pitch=awning['pitch'], overhang_ft=0)
                         for side in _SIDES])
    record['material'] = _roof_material(model, building)
    if 'plane_materials' in record:
        previous = record.pop('plane_materials')
        existing = record.get('notes', [])
        record['notes'] = ([existing] if isinstance(existing, str) else list(existing) if isinstance(existing, list) else [])
        record['notes'].append('Previously inactive awning plane materials: '+json.dumps(previous, sort_keys=True))
        notes.append(f"{record.get('name') or 'Awning'} keeps the building roof finish; its previously inactive plane finishes are retained in its notes.")
    own_materials = record.get('materials') if isinstance(record.get('materials'), dict) else {}
    parent_materials = parent.get('materials') if isinstance(parent.get('materials'), dict) else {}
    if 'gutter' not in own_materials and parent_materials.get('gutter'):
        record['materials'] = dict(own_materials, gutter=deepcopy(parent_materials['gutter']))
    local_outward = [0, sign] if axis == 0 else [sign, 0]
    angle = math.atan2(local_outward[0]*n[1]-local_outward[1]*n[0], sum(local_outward[i]*n[i] for i in (0, 1)))
    if abs(angle) > 1e-12:
        record['roof_frame'] = dict(origin=origin, angle=angle)
    original_count = awning.get('brackets', 0)
    if type(original_count) is float and math.isfinite(original_count) and original_count % 1 and capped:
        # The legacy loop rounded its iteration count up, but used the raw
        # fractional denominator for spacing. Ordinary authored overrides keep
        # those exact positions after the new whole-number count is stored.
        inset = min(.6, width/2)
        overrides = {}
        for i in range(capped):
            u = -width/2+inset+i*(width-2*inset)/max(1, original_count-1)
            overrides[str(i)] = [origin[k]+u*tangent[k]+awning['depth']*n[k] for k in (0, 1)]
        record['support']['at'] = overrides
    level = wall.get('level') if awning.get('wall') and wall else _level(building, awning['eave'], wall)
    if not level and building.get('levels'):
        level = min(building['levels'], key=lambda l: l.get('elevation', 0)).get('id')
    if level:
        record['level'] = level
    from services.twin_model_supports import wall_axis
    diagonal = wall is not None and wall_axis(wall['from'], wall['to']) is None
    other_floor = wall is not None and wall.get('level') != level
    if other_floor:
        old = wall
        wall = next((w for w in walls if w.get('level') == level
                     and w.get('exterior') and wall_axis(w['from'], w['to']) == 1-axis
                     and min(w['from'][axis], w['to'][axis])-_EPS <= span_mid <= max(w['from'][axis], w['to'][axis])+_EPS
                     and abs(w['from'][1-axis]+(span_mid-w['from'][axis])
                             *(w['to'][1-axis]-w['from'][1-axis])/(w['to'][axis]-w['from'][axis])-origin[1-axis]) < .01), None)
    edge = record['edges'][_SIDES.index(low)]
    for field in ('gutter', 'gutter_ack', 'downspouts'):
        if field in awning:
            edge[field] = deepcopy(awning[field])
    if wall and not diagonal and not malformed:
        record['host'] = dict(wall=wall['id'], edge=host_edge)
        edge = record['edges'][host_edge]
        along = axis
        edge.update(wall=wall['id'], wall_offset=record['area'][host_edge][1-axis]-wall['from'][1-axis],
                    wall_along_offset=record['area'][host_edge][along]-wall['from'][along])
    elif diagonal:
        _flag(building, record, notes, 'has a diagonal wall; its drawn position was kept without a host')
    elif other_floor and not malformed:
        _flag(building, record, notes, 'has no host wall on its floor; its drawn position was kept')
    else:
        reason = ('needs its span and depth set before it can be placed' if malformed else
                  'has lost its supporting wall; place it again')
        record.update(state='ghost', why=f"{record.get('name') or 'Awning'} {reason}.",
                      position=[sum(p[i] for p in record['area'])/4 for i in (0, 1)])
        _flag(building, record, notes, reason)
    return record


def _shed(extension, parent, pid):
    malformed = not all(_number(extension.get(k)) for k in ('to_x', 'pitch')) or extension['to_x'] <= parent['rect'][2]
    from services.twin_model_roofs import from_section
    x0, y0, x1, y1 = parent['rect']
    value = {k: deepcopy(v) for k, v in extension.items() if k not in ('section', 'to_x', 'kind')}
    end = x1+1 if malformed else extension['to_x']
    pitch = extension['pitch'] if _number(extension.get('pitch')) else 3
    value.update(id=pid, kind='shed', low_side='x1', rect=[x1, y0, end, y1], pitch=pitch,
                 plate=parent['plate']-(end-x1)*pitch/12,
                 overhang=0, level=parent.get('level'),
                 edges=[dict(overhang_ft=v) for v in (parent.get('overhang', 0), extension.get('overhang', 0),
                                                      parent.get('overhang', 0), 0)])
    if malformed:
        value.update(state='ghost', why='This shed roof needs an outer edge beyond its parent. Place it again or delete it.',
                     position=[x1, (y0+y1)/2], support=dict(kind='bracket', count=0))
    return from_section(value)


def migrate_awnings(model):
    """Copy either a connected model or a flat plan; migrate attachments once."""
    if not isinstance(model, dict) or not any(
            isinstance(e, dict) and e.get('kind') in _KINDS
            for b in model.get('buildings', []) if isinstance(b, dict)
            for container in (b, b.get('roof', {})) if isinstance(container, dict)
            for e in (container.get('extensions', []) if isinstance(container.get('extensions'), list) else [])):
        return model, []
    result, notes = deepcopy(model), []
    native_schema = result.get('schema') == 'chauffeur.twin.plan/3'
    for building in result.get('buildings', []):
        if not isinstance(building, dict):
            continue
        native = native_schema or 'roofs' in building and 'roof' not in building
        container = building if native else building.get('roof', {})
        extensions = container.get('extensions', [])
        if not isinstance(extensions, list) or not any(isinstance(e, dict) and e.get('kind') in _KINDS for e in extensions):
            continue
        from services.twin_model_roofs import to_sections
        sections = container.get('sections', []) if not native else []
        if native:
            for roof in building.get('roofs', []):
                try:
                    sections.extend(to_sections(roof))
                except (KeyError, TypeError, ValueError, IndexError):
                    # A diagnostic ghost can lack a usable parent outline;
                    # the attachment still retains enough data to survive.
                    continue
        by_id = {s.get('id'): s for s in sections}
        walls = _lines(building)
        target = building.setdefault('roofs', []) if native else container.setdefault('sections', [])
        used = {r.get('id') for r in target}
        kept = []
        for index, extension in enumerate(extensions):
            if not isinstance(extension, dict) or extension.get('kind') not in _KINDS:
                kept.append(extension); continue
            parent = by_id.get(extension.get('section'))
            if parent is None:
                # An orphan awning still has its span, depth and eave. Its
                # saved position or zero supplies the former front wall line.
                position = extension.get('position', [0, 0])
                line = position[1] if isinstance(position, (list, tuple)) and len(position) == 2 else 0
                parent = dict(rect=[extension.get('x0', 0), line, extension.get('x1', 1), line+1], plate=extension.get('eave', 8))
            pid = extension.get('id') or f"{extension['kind']}-{index+1}"
            if pid in used:
                serial, base = 2, pid
                while pid in used:
                    pid = f'{base}-{serial}'; serial += 1
            record = (_awning(result, building, extension, parent, walls, pid, notes) if extension['kind'] == 'awning'
                      else _shed(extension, parent, pid))
            if record is None:
                kept.append(extension); continue
            if extension['kind'] == 'shed_continuation' and record.get('why'):
                _flag(building, record, notes, record['why'].rstrip('.'))
            used.add(pid)
            if not record.get('why') and parent.get('id') == 'roof-main' and parent.get('kind') == 'gable' and parent.get('ridge') == 'y':
                parent['gable_beam'] = True
                if native:
                    original = next((r for r in building['roofs'] if r['id'] == (parent.get('roof') or parent['id'])), None)
                    if original is not None:
                        original['gable_beam'] = True
            converted = record if native else to_sections(record)[0]
            target.append(converted)
            # Flat views retain connected records as editor extras; keep that
            # cache in agreement while leaving all existing roofs untouched.
            if not native and isinstance(building.get('roofs'), list):
                building['roofs'].append(record)
            notes.append(f"Converted {record.get('name') or ('Awning' if extension['kind'] == 'awning' else 'Shed roof')} to an ordinary roof.")
        container['extensions'] = kept
        if not native and isinstance(building.get('extensions'), list):
            building['extensions'] = [e for e in building['extensions'] if e.get('kind') not in _KINDS]
    return result, notes
