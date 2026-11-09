"""Pure roof sections from block geometry and observed photo sides.

The plan supplies measurements, never end styles. Coordinates are in feet,
with the street at y0. Per-side pitches place a shared ridge using the same
two intersecting eave planes as twin_roof.js.
"""

from copy import deepcopy
from math import isfinite
from services.twin_plan import _roof_entries


_SIDES = {'left': 'x0', 'right': 'x1', 'front': 'y0', 'rear': 'y1'}
_STYLES = {'gable_end': 'gable', 'clipped_gable_end': 'clip', 'slope': 'hip'}
_UNSEEN = ('hidden', 'conflict')


def _number(value, default):
    return value if type(value) in (int, float) and isfinite(value) else default


def _pitch(value):
    return max(3, min(14, _number(value, 8)))


def _across(section):
    return (1, ('y0', 'y1')) if section['ridge'] == 'x' else (0, ('x0', 'x1'))


def _ridge(section):
    if section['kind'] == 'flat':
        return (section['rect'][1] + section['rect'][3]) / 2, section['plate']
    if section['kind'] == 'shed':
        axis = 0 if section['low_side'].startswith('x') else 1
        rect = section['rect']
        pitch = section.get('pitches', {}).get(section['low_side'], section['pitch'])
        high = rect[axis + (2 if section['low_side'].endswith('0') else 0)]
        return high, section['plate'] + (rect[axis + 2] - rect[axis]) * pitch / 12
    axis, ends = _across(section)
    lo, hi = section['rect'][axis], section['rect'][axis + 2]
    pitches = section.get('pitches', {})
    a, b = (pitches.get(end, section['pitch']) / 12 for end in ends)
    at = (a * lo + b * hi) / (a + b)
    return at, section['plate'] + a * (at - lo)


def _shared_edge(a, b, along=None):
    """Share a wall edge (within the block snap tolerance), not just a corner."""
    shared = 0
    for axis in (0, 1) if along is None else (along,):
        other = 1 - axis
        gap = min(abs(a[axis + 2] - b[axis]), abs(b[axis + 2] - a[axis]))
        overlap = min(a[other + 2], b[other + 2]) - max(a[other], b[other])
        if gap <= .5 and overlap > .5:
            shared = max(shared, overlap)
    return shared


def _neighbours(a, b, along=None):
    return _shared_edge(a, b, along) > 0


def _shared_end(block, blocks, side):
    end = _SIDES[side]
    axis = 0 if end.startswith('x') else 1
    other = 1 - axis
    rect = block['rect']
    edge = axis + (2 if end.endswith('1') else 0)
    opposite = axis + (0 if end.endswith('1') else 2)
    return any(neighbour is not block
               and abs(rect[edge] - neighbour['rect'][opposite]) <= .5
               and min(rect[other + 2], neighbour['rect'][other + 2])
                   - max(rect[other], neighbour['rect'][other]) >= (rect[other + 2] - rect[other]) / 2
               for neighbour in blocks)


def _end_flags(block, blocks, section, observations):
    kinds = {side: observations.get('sides', {}).get(side, {}).get('kind', 'hidden') for side in _SIDES}
    place = 'The roof over the ' + _place(block, blocks)[4:-5]
    flags = []
    for kind in ('hidden', 'conflict'):
        sides = [side for side, end in _SIDES.items() if end.startswith(section['ridge'])
                 and kinds[side] == kind and not _shared_end(block, blocks, side)]
        if not sides:
            continue
        plural = len(sides) > 1
        subject = ' and '.join(sides) + (' ends' if plural else ' end')
        reason = ('were' if plural else 'was') + ' not visible in the photos' if kind == 'hidden' else (
            'look different between photos' if plural else 'looks different between photos')
        styles = [section.get('ends', {}).get(_SIDES[side], section['kind']) for side in sides]
        made = ('them ' + ('hips' if all(s == 'hip' for s in styles) else 'gables') if plural else
                'it a ' + ('hip' if styles[0] == 'hip' else 'gable'))
        flag = {'block': block['id'], 'sides': sides,
                'text': f'{place}: its {subject} {reason}; I made {made}.'}
        if not plural:
            flag['side'] = sides[0]
        flags.append(flag)
    return flags


def _place(block, blocks):
    """Describe a position without leaking generated ids into a build log."""
    def centre(b, axis):
        return (b['rect'][axis] + b['rect'][axis + 2]) / 2

    def area(b):
        r = b['rect']
        return (r[2] - r[0]) * (r[3] - r[1])

    extent = [(min(b['rect'][a] for b in blocks), max(b['rect'][a + 2] for b in blocks))
              for a in (0, 1)]

    def words(b):
        positions = []
        for axis, labels in ((0, ('left', 'middle', 'right')), (1, ('front', '', 'rear'))):
            lo, hi = extent[axis]
            at = centre(b, axis)
            positions.append(labels[0] if at < lo + (hi - lo) / 3 else
                             labels[2] if at > hi - (hi - lo) / 3 else labels[1])
        if b.get('storey') == 'upper':
            positions.append('upper')
        return tuple(w for w in positions if w)

    position = words(block)
    peers = [b for b in blocks if words(b) == position]
    qualifiers = []
    # Resolve shared coarse positions using size, then progressively finer
    # positions. Every qualifier comes from geometry, never a generated id.
    while len(peers) > 1:
        measures = [(area, ('small', 'large')),
                    (lambda b: centre(b, 0), ('further left', 'further right')),
                    (lambda b: centre(b, 1), ('further front', 'further rear'))]
        for measure, labels in measures:
            lo, hi = min(map(measure, peers)), max(map(measure, peers))
            if hi - lo > 1e-9:
                midpoint = (lo + hi) / 2
                lower = measure(block) <= midpoint
                qualifiers.append(labels[0] if lower else labels[1])
                peers = [b for b in peers if (measure(b) <= midpoint) == lower]
                break
        else:
            break  # Coincident, identical blocks have no distinct physical place.
    return 'The ' + ' '.join(qualifiers + list(position) + ['roof'])


def _align_ridges(sections, fixed):
    """Align connected parallel gables, retaining each block's mean pitch.

    Solving for the two eave pitches keeps rects and plates on their walls.
    Intersect their feasible intervals first so no slope leaves 3..14.
    A person's section is an immovable anchor.
    """
    excluded = set()
    remaining = {i for i, s in enumerate(sections) if s['kind'] == 'gable'}
    while remaining:
        first = min(remaining)
        group, pending = [], [first]
        remaining.remove(first)
        while pending:
            i = pending.pop()
            group.append(i)
            s = sections[i]
            along = 0 if s['ridge'] == 'x' else 1
            for j in sorted(remaining):
                t = sections[j]
                if s['ridge'] == t['ridge'] and _neighbours(s['rect'], t['rect'], along):
                    remaining.remove(j)
                    pending.append(j)
        if len(group) < 2:
            continue
        intervals = {}
        for i in group:
            s = sections[i]
            axis, _ = _across(s)
            lo, hi = s['rect'][axis], s['rect'][axis + 2]
            scale = (hi - lo) / (2 * s['pitch'])
            low = max(lo + 3 * scale, hi - 14 * scale)
            high = min(lo + 14 * scale, hi - 3 * scale)
            if i in fixed:
                low = high = _ridge(s)[0]
            intervals[i] = low, high
        lower = max(low for low, high in intervals.values())
        upper = min(high for low, high in intervals.values())
        if lower > upper + 1e-9:
            # At an interval boundary every feasible run can be found among
            # the blocks containing that point. Only connected runs count.
            along = 0 if sections[first]['ridge'] == 'x' else 1
            adjacency = {i: {j for j in group if j != i and
                            _neighbours(sections[i]['rect'], sections[j]['rect'], along)}
                         for i in group}
            runs = []
            for point in sorted({v for interval in intervals.values() for v in interval}):
                available = {i for i, (low, high) in intervals.items() if low <= point <= high}
                while available:
                    run, pending = set(), [min(available)]
                    while pending:
                        i = pending.pop()
                        if i not in available:
                            continue
                        available.remove(i)
                        run.add(i)
                        pending.extend(adjacency[i] & available)
                    runs.append(tuple(sorted(run)))
            selected = min(runs, key=lambda run: (-len(run), run))
            excluded.update(set(group) - set(selected))
            group = selected
            lower = max(intervals[i][0] for i in group)
            upper = min(intervals[i][1] for i in group)
        target = sum(_ridge(sections[i])[0] for i in group) / len(group)
        target = max(lower, min(upper, target))
        for i in group:
            if i in fixed:
                continue
            s = sections[i]
            axis, ends = _across(s)
            lo, hi = s['rect'][axis], s['rect'][axis + 2]
            if abs(_ridge(s)[0] - target) < 1e-9:
                continue
            s['pitches'] = {
                ends[0]: _pitch(2 * s['pitch'] * (hi - target) / (hi - lo)),
                ends[1]: _pitch(2 * s['pitch'] * (target - lo) / (hi - lo)),
            }
    return excluded


def _inherit_unseen(blocks, sections, observations, fixed):
    unseen = {i for i, b in enumerate(blocks) if i not in fixed and
              all(observations.get(b['id'], {}).get('sides', {}).get(side, {}).get('kind', 'hidden')
                  in _UNSEEN for side in _SIDES)}
    known = set(range(len(blocks))) - unseen
    while unseen:
        inferred = {}
        for i in sorted(unseen):
            neighbours = [(j, _shared_edge(sections[i]['rect'], sections[j]['rect'])) for j in known]
            neighbours = [(j, length) for j, length in neighbours if length]
            if neighbours:
                # A geometry tie-break keeps this independent of input order.
                j, _ = min(neighbours, key=lambda pair: (-pair[1], tuple(sections[pair[0]]['rect'])))
                inferred[i] = sections[j]
        if not inferred:
            break
        for i, neighbour in inferred.items():
            section = sections[i]
            section['kind'], section['ridge'] = neighbour['kind'], neighbour['ridge']
            section.pop('ends', None)
            if section['kind'] == 'shed':
                section['low_side'] = neighbour['low_side']
            elif section['kind'] == 'flat':
                section['pitch'] = 0
        unseen.difference_update(inferred)
        known.update(inferred)


def _dormers(block, section, sides, evidence, flags, place):
    result = []
    axis, eaves = _across(section)
    along = 1 - axis
    rect = section['rect']
    ridge_at, _ = _ridge(section)
    for side, end in _SIDES.items():
        photo = sides.get(side, {})
        targets = [d for d in evidence.get('dormers', [])
                   if d.get('side') == side and _number(d.get('centre'), None) is not None]
        if end not in eaves:
            continue
        if photo.get('kind') == 'slope' and targets:
            flags.append({'block': block['id'], 'side': side, 'text':
                          f'{place} shows a plain slope instead of the drawn dormer on its {side} side; please check it.'})
        drawings_only = photo.get('kind', 'hidden') in _UNSEEN and bool(targets)
        if photo.get('kind') != 'dormer' and not drawings_only:
            continue
        if drawings_only:
            flags.append({'block': block['id'], 'side': side, 'text':
                          f'{place} has a dormer on its {side} side from the drawings only; please check it.'})
        centre = _number(photo.get('centre'), None)
        target = min(targets, key=lambda d: abs(d['centre'] - centre)) if targets and centre is not None else (
            targets[0] if targets else {})
        if target and (centre is None or abs(target['centre'] - centre) <= 2):
            centre, width = target['centre'], target.get('width', photo.get('width'))
        else:
            width = photo.get('width')
        lo, hi = rect[along], rect[along + 2]
        width = max(.5, min(hi - lo, _number(width, (hi - lo) / 3)))
        centre = max(lo + width / 2, min(hi - width / 2, _number(centre, (lo + hi) / 2)))
        dormer_rect = list(rect)
        dormer_rect[along], dormer_rect[along + 2] = centre - width / 2, centre + width / 2
        if end.endswith('0'):
            dormer_rect[axis + 2] = ridge_at
        else:
            dormer_rect[axis] = ridge_at
        result.append({**deepcopy(section), 'id': f"roof-{block['id']}-dormer-{len(result) + 1}",
                       'kind': 'gable', 'ridge': 'y' if section['ridge'] == 'x' else 'x',
                       'rect': dormer_rect})
        # The cross gable has its own two plain gable ends and symmetric pitch.
        result[-1].pop('ends', None)
        result[-1].pop('pitches', None)
        result[-1].pop('block', None)
        result[-1]['dormer_of'] = list(block['rect'])
    return result


def derive_roof(blocks, observations, evidence, choices):
    """Return (plan-schema sections, plain review flags), without mutating inputs.

    Person choices match all four rect edges within one foot and are applied
    before alignment or checks. Missing/conflicting photo sides default to a
    gable; a wholly unseen block follows an adjacent roof and gets one review line.
    """
    sections, flags, fixed = [], [], set()
    choices = _roof_entries({'choices': choices}, 'choices')
    used_choices = set()
    for block in blocks:
        key, rect = block['id'], block['rect']
        obs, plan = observations.get(key, {}), evidence.get(key, {})
        sides = obs.get('sides', {})
        kinds = {side: sides.get(side, {}).get('kind', 'hidden') for side in _SIDES}
        votes = {axis: sum(kinds[side] in ('gable_end', 'clipped_gable_end')
                           for side, end in _SIDES.items() if end.startswith(axis)) for axis in ('x', 'y')}
        fallback = plan.get('ridge')
        if fallback not in ('x', 'y'):
            fallback = 'x' if rect[2] - rect[0] >= rect[3] - rect[1] else 'y'
        ridge = max(votes, key=votes.get) if votes['x'] != votes['y'] else fallback
        ends = {_SIDES[side]: _STYLES.get(kind, 'gable') for side, kind in kinds.items()
                if _SIDES[side].startswith(ridge)}
        kind = 'hip' if all(style == 'hip' for style in ends.values()) else 'gable'
        plan_pitch, photo_pitch = _number(plan.get('pitch'), None), _number(obs.get('pitch'), None)
        pitch = _pitch(plan_pitch if plan_pitch is not None else photo_pitch)
        section = {'id': f'roof-{key}', 'rect': list(rect), 'block': list(rect),
                   'level': block['level'], 'kind': kind, 'ridge': ridge, 'ends': ends,
                   'plate': block['plate'], 'pitch': pitch, 'overhang': 1,
                   'pitch_source': 'drawn' if plan_pitch is not None else 'photos' if photo_pitch is not None else 'default',
                   'src': {'sheet': '', 'page': 0, 'step': 'roof_blocks'}}
        matches = [(max(abs(a - b) for a, b in zip(rect, c['rect'])), i, c)
                   for i, c in enumerate(choices) if i not in used_choices
                   and isinstance(c.get('rect'), (list, tuple)) and len(c['rect']) == 4]
        match = min(matches, key=lambda item: (item[0], item[1])) if matches else None
        if match and match[0] <= 1:
            _, choice_index, choice = match
            used_choices.add(choice_index)
            fixed.add(len(sections))
            for field in ('kind', 'ridge', 'pitch', 'plate', 'overhang', 'low_side'):
                if field in choice:
                    section[field] = deepcopy(choice[field])
            # A changed kind must inherit its own ends, not the photo's form.
            if 'kind' in choice:
                section.pop('ends', None)
            elif section['ridge'] != ridge:
                section['ends'] = {_SIDES[side]: _STYLES.get(kind, 'gable') for side, kind in kinds.items()
                                   if _SIDES[side].startswith(section['ridge'])}
                if all(style == 'gable' for style in section['ends'].values()):
                    section.pop('ends')
            if 'ends' in choice:
                section['ends'] = deepcopy(choice['ends'])
            if section['kind'] in ('shed', 'flat'):
                section.pop('ends', None)
                if section['kind'] == 'shed':
                    section.setdefault('low_side', 'y0' if section['ridge'] == 'x' else 'x0')
            if 'pitch' in choice:
                section['pitch_source'] = 'person'
            if section['kind'] == 'flat':
                section['pitch'] = 0
            elif section['kind'] in ('gable', 'hip'):
                section['pitch'] = _pitch(section['pitch'])
        else:
            place = _place(block, blocks)
            if not all(kind in _UNSEEN for kind in kinds.values()):
                for side, kind in kinds.items():
                    if kind in ('gable_end', 'clipped_gable_end') and not _SIDES[side].startswith(section['ridge']):
                        flags.append({'block': key, 'side': side, 'text':
                                      f'{place}: the {side} side shows a gable end where this roof has an eave; please check it.'})
                    elif kind == 'dormer' and _SIDES[side].startswith(section['ridge']):
                        flags.append({'block': key, 'side': side, 'text':
                                      f'{place}: the {side} side shows a dormer where this roof has an end; please check it.'})
        sections.append(section)

    # Photos decide as-built relative slopes. If plan pitches contradict a
    # visible comparison, use that block's own photo estimate. A neighbour's
    # photo pitch is needed only when its plan pitch still reverses the pair.
    photo_pitches = set()
    for i, block in enumerate(blocks):
        obs = observations.get(block['id'], {})
        relative = obs.get('slope_vs_neighbours')
        if i in fixed or relative not in ('lower', 'steeper'):
            continue
        for j, neighbour in enumerate(blocks):
            if i == j or not _neighbours(block['rect'], neighbour['rect']):
                continue
            own = _number(obs.get('pitch'), None)
            other = _number(observations.get(neighbour['id'], {}).get('pitch'), None)
            if own is None:
                continue
            direction = 1 if relative == 'lower' else -1
            if direction * (sections[i]['pitch'] - sections[j]['pitch']) >= 0:
                photo_pitches.add(i)
                if (j not in fixed and other is not None
                        and direction * (_pitch(own) - sections[j]['pitch']) >= 0
                        and direction * (_pitch(own) - _pitch(other)) < 0):
                    photo_pitches.add(j)
    for i in photo_pitches:
        sections[i]['pitch'] = _pitch(observations[blocks[i]['id']]['pitch'])
        sections[i]['pitch_source'] = 'photos'

    _inherit_unseen(blocks, sections, observations, fixed)
    wholly_unseen = set()
    for i, (block, section) in enumerate(zip(blocks, sections)):
        if i in fixed:
            continue
        obs = observations.get(block['id'], {})
        flags.extend(_end_flags(block, blocks, section, obs))
        if all(obs.get('sides', {}).get(side, {}).get('kind', 'hidden') in _UNSEEN for side in _SIDES):
            wholly_unseen.add(block['id'])
            if not any(f['block'] == block['id'] for f in flags):
                flags.append({'block': block['id'], 'text':
                              f'{_place(block, blocks)} was not visible in the photos; please check its roof form.'})
    for i in sorted(_align_ridges(sections, fixed) - fixed):
        block = blocks[i]
        # Keep the single review line promised for a wholly unseen block.
        text = f'{_place(block, blocks)}: its ridge could not line up with its neighbours; please check its slope.'
        unseen_flag = next((f for f in flags if f['block'] == block['id']
                            and block['id'] in wholly_unseen), None)
        if unseen_flag:
            unseen_flag['text'] += ' Its ridge could not line up with its neighbours; please check its slope.'
        else:
            flags.append({'block': block['id'], 'text': text})
    for i, (block, section) in enumerate(zip(blocks, sections)):
        if i in fixed or observations.get(block['id'], {}).get('slope_vs_neighbours') != 'same':
            continue
        for j, other in enumerate(sections):
            if (i != j and observations.get(blocks[j]['id'], {}).get('slope_vs_neighbours') == 'same'
                    and _neighbours(section['rect'], other['rect'])
                    and _ridge(section)[1] > _ridge(other)[1] + 6):
                # A wholly unseen block already has its single review line.
                text = f'{_place(block, blocks)} stands more than six feet above a neighbouring ridge; please check its height.'
                unseen_flag = next((f for f in flags if f['block'] == block['id']
                                    and block['id'] in wholly_unseen), None)
                if unseen_flag:
                    unseen_flag['text'] += ' ' + text
                else:
                    flags.append({'block': block['id'], 'text':
                                  text})
                break

    dormers = []
    for i, (block, section) in enumerate(zip(blocks, sections)):
        if section['kind'] in ('gable', 'hip'):
            dormers.extend(_dormers(block, section, observations.get(block['id'], {}).get('sides', {}),
                                    evidence.get(block['id'], {}), flags if i not in fixed else [],
                                    _place(block, blocks)))
    # A completely unseen roof gets one review line, including any other checks.
    for key in wholly_unseen:
        mine = [f for f in flags if f['block'] == key]
        if len(mine) > 1:
            mine[0]['text'] = ' '.join(f['text'] for f in mine)
            mine[0]['sides'] = list(dict.fromkeys(side for f in mine for side in f.get('sides', [])))
            flags = [f for f in flags if f['block'] != key or f is mine[0]]
    return sections + dormers, flags
