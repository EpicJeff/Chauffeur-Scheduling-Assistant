"""Pure roof sections from block geometry and observed photo sides.

The plan supplies measurements, never end styles. Coordinates are in feet,
with the street at y0. Per-side pitches place a shared ridge using the same
two intersecting eave planes as twin_roof.js.
"""

from copy import deepcopy
from math import isfinite


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


def _neighbours(a, b, along=None):
    """Share a wall edge (within the block snap tolerance), not just a corner."""
    for axis in (0, 1) if along is None else (along,):
        other = 1 - axis
        gap = min(abs(a[axis + 2] - b[axis]), abs(b[axis + 2] - a[axis]))
        overlap = min(a[other + 2], b[other + 2]) - max(a[other], b[other])
        if gap <= .5 and overlap > .5:
            return True
    return False


def _place(block, blocks):
    """Describe a position without leaking generated ids into a build log."""
    centres = [(b['rect'][0] + b['rect'][2]) / 2 for b in blocks]
    centre = (block['rect'][0] + block['rect'][2]) / 2
    lo, hi = min(centres), max(centres)
    side = ('left ' if centre < lo + (hi - lo) / 3 else
            'right ' if centre > hi - (hi - lo) / 3 else 'middle ') if hi > lo else ''
    upper = 'upper ' if block.get('storey') == 'upper' else ''
    return f'The {side}{upper}roof'


def _align_ridges(sections, fixed):
    """Align connected parallel gables, retaining each block's mean pitch.

    Solving for the two eave pitches keeps rects and plates on their walls.
    Intersect their feasible intervals first so no slope leaves 3..14.
    A person's section is an immovable anchor.
    """
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
        lower, upper = -float('inf'), float('inf')
        for i in group:
            s = sections[i]
            axis, _ = _across(s)
            lo, hi = s['rect'][axis], s['rect'][axis + 2]
            scale = (hi - lo) / (2 * s['pitch'])
            low = max(lo + 3 * scale, hi - 14 * scale)
            high = min(lo + 14 * scale, hi - 3 * scale)
            if i in fixed:
                low = high = _ridge(s)[0]
            lower, upper = max(lower, low), min(upper, high)
        if lower > upper + 1e-9:
            # Incompatible measured pitches must not be silently replaced.
            continue
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


def _dormers(block, section, sides, evidence):
    result = []
    axis, eaves = _across(section)
    along = 1 - axis
    rect = section['rect']
    ridge_at, _ = _ridge(section)
    for side, end in _SIDES.items():
        photo = sides.get(side, {})
        if photo.get('kind') != 'dormer' or end not in eaves:
            continue
        centre = _number(photo.get('centre'), None)
        targets = [d for d in evidence.get('dormers', [])
                   if d.get('side') == side and _number(d.get('centre'), None) is not None]
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
    return result


def derive_roof(blocks, observations, evidence, choices):
    """Return (plan-schema sections, plain review flags), without mutating inputs.

    Person choices match all four rect edges within one foot and are applied
    before alignment or checks. Missing/conflicting photo sides default to a
    gable; a wholly unseen block gets just one review line.
    """
    sections, flags, fixed = [], [], set()
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
        pitch = _pitch(plan.get('pitch', obs.get('pitch', 8)))
        section = {'id': f'roof-{key}', 'rect': list(rect), 'block': list(rect),
                   'level': block['level'], 'kind': kind, 'ridge': ridge, 'ends': ends,
                   'plate': block['plate'], 'pitch': pitch, 'overhang': 1,
                   'pitch_source': 'drawn' if 'pitch' in plan else 'photos' if 'pitch' in obs else 'default',
                   'src': {'sheet': '', 'page': 0, 'step': 'roof_blocks'}}
        matches = [(max(abs(a - b) for a, b in zip(rect, c['rect'])), i, c)
                   for i, c in enumerate(choices) if i not in used_choices
                   and isinstance(c.get('rect'), (list, tuple)) and len(c['rect']) == 4]
        match = min(matches, key=lambda item: (item[0], item[1])) if matches else None
        if match and match[0] <= 1:
            _, choice_index, choice = match
            used_choices.add(choice_index)
            fixed.add(len(sections))
            for field in ('kind', 'ridge', 'pitch', 'plate', 'overhang'):
                if field in choice:
                    section[field] = deepcopy(choice[field])
            # A changed kind must inherit its own ends, not the photo's form.
            if 'kind' in choice:
                section.pop('ends', None)
            elif section['ridge'] != ridge:
                section['ends'] = {section['ridge'] + end[-1]: style for end, style in ends.items()}
            if 'ends' in choice:
                section['ends'] = deepcopy(choice['ends'])
            if section['kind'] in ('shed', 'flat'):
                section.pop('ends', None)
                if section['kind'] == 'shed':
                    section['low_side'] = 'y0' if section['ridge'] == 'x' else 'x0'
            if 'pitch' in choice:
                section['pitch_source'] = 'person'
            if section['kind'] == 'flat':
                section['pitch'] = 0
        else:
            place = _place(block, blocks)
            if all(kind in _UNSEEN for kind in kinds.values()):
                flags.append({'block': key, 'text': f'{place} was not visible in the photos; its ends default to gables.'})
            else:
                for side, kind in kinds.items():
                    if kind in _UNSEEN:
                        reason = 'was not visible in the photos' if kind == 'hidden' else 'looks different between photos'
                        flags.append({'block': key, 'side': side,
                                      'text': f'{place}: the {side} side {reason}; please check it.'})
        sections.append(section)

    _align_ridges(sections, fixed)
    for i, (block, section) in enumerate(zip(blocks, sections)):
        if i in fixed or observations.get(block['id'], {}).get('slope_vs_neighbours') != 'same':
            continue
        for j, other in enumerate(sections):
            if (i != j and observations.get(blocks[j]['id'], {}).get('slope_vs_neighbours') == 'same'
                    and _neighbours(section['rect'], other['rect'])
                    and _ridge(section)[1] > _ridge(other)[1] + 6):
                # A wholly unseen block already has its single review line.
                if not any(f['block'] == block['id'] and 'side' not in f for f in flags):
                    flags.append({'block': block['id'], 'text':
                                  f'{_place(block, blocks)} stands more than six feet above a neighbouring ridge; please check its height.'})
                break

    dormers = []
    for block, section in zip(blocks, sections):
        if section['kind'] in ('gable', 'hip'):
            dormers.extend(_dormers(block, section, observations.get(block['id'], {}).get('sides', {}),
                                    evidence.get(block['id'], {})))
    return sections + dormers, flags
