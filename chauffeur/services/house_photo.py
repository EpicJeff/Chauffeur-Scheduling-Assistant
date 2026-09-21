"""Photo observations and structural checks, independent of provider and storage."""
import copy
import math

OBSERVATION_PROMPT = """Inspect the attached house photo before designing anything. Return JSON only.
Describe VISIBLE architecture, not a slot configuration. All at/width values are fractions
of the entire visible front facade, left to right in the PHOTO. at is the LEFT EDGE,
not the centre. Exclude landscaping, driveway, and unseen side elevations from this width.
Distinguish a full second-story rectangular wall (windows below its eave) from a triangular
attic gable or dormer. Do not turn every tall gable into a second story.
Return this exact shape:
{"viewpoint":"left|centre|right", "garage_side":"left|right|unknown",
 "sections":[{"description":"visible section and roof direction", "at":0.0,"width":0.3}],
 "roofs":[{"at":0.6,"width":0.35,"story":1,"ridge":"x|z|unknown",
           "front_gable":"cross|end|none|unknown","evidence":"visible roof planes supporting this reading"}],
 "upper":[{"at":0.3,"width":0.4,"windows":3}],
 "porches":[{"at":0.3,"width":0.4}],
 "gables":[{"at":0.7,"width":0.3}],
 "materials":["material and the region where it appears"],
 "uncertain":["features obscured or not inferable"]}
Arrays may be empty. windows counts visible window units/groups, not panes.
gables describes street-facing triangular roof ends, including those above upper stories.
Do not infer a left/front garage merely because no garage door appears in the photo.
Record each underlying roof volume separately in roofs. x means ridge parallel to the
front facade; z means ridge running front-to-back. A visible front triangle does NOT
establish ridge=z: a cross-gable can project from a ridge=x roof running behind it.
Inspect the roof planes and continuous eave behind/beside the triangle. Use unknown
when hidden; do not invent evidence. front_gable=cross means an added projecting gable;
end means the end of the underlying ridge=z roof. story is the supporting rectangular
wall's story count, NOT the count of window rows. A window in an attic triangle does
not create an upper[] entry. Keep porch entrance gables separate from main roof volumes.
Record unknown garage side explicitly. Describe porch slopes and entrance gables in sections.
"""


def validate_observations(value):
    if not isinstance(value, dict):
        return ['observations must be an object']
    errors = []
    for key, choices in [('viewpoint', ('left', 'centre', 'right')),
                         ('garage_side', ('left', 'right', 'unknown'))]:
        if value.get(key) not in choices:
            errors.append('invalid ' + key)
    for key in ('sections', 'upper', 'porches', 'gables', 'roofs'):
        if key == 'roofs' and key not in value:
            continue  # older cached observations remain usable
        rows = value.get(key)
        if not isinstance(rows, list) or len(rows) > 24:
            errors.append('invalid ' + key)
            continue
        for row in rows:
            if not isinstance(row, dict):
                errors.append('invalid ' + key + ' region'); continue
            a, w = row.get('at'), row.get('width')
            if (type(a) not in (int, float) or type(w) not in (int, float)
                    or not math.isfinite(a) or not math.isfinite(w)
                    or not 0 <= a < 1 or not 0 < w <= 1 or a + w > 1.01):
                errors.append('invalid ' + key + ' bounds')
            if key == 'roofs':
                if (type(row.get('story')) is not int or row['story'] not in (1, 2)
                        or row.get('ridge') not in ('x', 'z', 'unknown')
                        or row.get('front_gable') not in ('cross', 'end', 'none', 'unknown')
                        or not isinstance(row.get('evidence'), str) or not row['evidence'].strip()):
                    errors.append('invalid roof interpretation')
            if key == 'upper' and (type(row.get('windows')) is not int or not 0 <= row['windows'] <= 40):
                errors.append('invalid upstairs window count')
    for key in ('materials', 'uncertain'):
        if not isinstance(value.get(key), list) or any(not isinstance(x, str) for x in value[key]):
            errors.append('invalid ' + key)
    if not value.get('sections'):
        errors.append('no visible sections identified')
    return errors


def reconcile_observations(value):
    """Soften contradictory interpretations after schema validation, without guessing.

    The original response is retained separately in the photo trace. Both disputed
    labels become unknown; positions, story counts and visible evidence survive.
    """
    result = copy.deepcopy(value)
    for i, roof in enumerate(result.get('roofs', [])):
        ridge, gable = roof['ridge'], roof['front_gable']
        if (ridge, gable) not in (('z', 'cross'), ('x', 'end')):
            continue
        roof['ridge'] = roof['front_gable'] = 'unknown'
        result['uncertain'].append(
            f'Roof region {i + 1}: conflicting ridge={ridge} and front_gable={gable}; '
            'both interpretations marked unknown. Recheck visible roof planes before choosing the structure.')
    return result


def structural_issues(spec, observations, slot_count=18):
    """Compare image-relative regions, allowing one slot and modest photo perspective error."""
    if not observations:
        return []
    issues = []
    side = observations['garage_side']
    if side != 'unknown' and bool(spec['mirror']) != (side == 'right'):
        issues.append('Garage orientation contradicts the photo.')

    def region(row):
        a, w = row['slot'] / slot_count, row['span'] / slot_count
        return (1 - a - w if spec['mirror'] else a), w

    def matches(row, observed):
        a, w = region(row)
        return abs(a - observed['at']) <= 0.13 and abs(w - observed['width']) <= 0.16

    used = set()
    for i, observed in enumerate(observations['upper']):
        candidates = [(j, u) for j, u in enumerate(spec['upper']) if j not in used and matches(u, observed)]
        if not candidates:
            issues.append(f'Second-story region {i + 1} has the wrong position or width.')
            continue
        j, upper = min(candidates, key=lambda pair: abs(region(pair[1])[0] - observed['at']))
        used.add(j)
        windows = [g for g in spec['ground'] if g['kind'] == 'window' and g.get('story', 1) == 2
                   and upper['slot'] <= g['slot'] and g['slot'] + g['span'] <= upper['slot'] + upper['span']]
        if len(windows) != observed['windows']:
            issues.append(f"Second-story region {i + 1} needs {observed['windows']} visible window groups; draft has {len(windows)}.")
    if len(used) < len(spec['upper']):
        issues.append('Draft has an unsupported or misplaced second-story section.')
    porches = [g for g in spec['ground'] if g['kind'] == 'porch']
    for i, observed in enumerate(observations['porches']):
        if not any(matches(p, observed) for p in porches):
            issues.append(f'Porch region {i + 1} has the wrong position or coverage.')
    gables = [r for r in spec['roof'] if r['kind'] == 'gable']
    gables += [u for u in spec['upper'] if u['roof']['form'] == 'gable' and u['roof']['ridge'] == 'z']
    # A block can itself present a gable without a separate roof feature.
    for name, start, count in [('garage', 0, 6), ('main', 6, slot_count - 6)]:
        roof = spec['blocks'][name]['roof']
        if roof['form'] == 'gable' and roof['ridge'] == 'z':
            gables.append({'slot': start, 'span': count})
    # Porch gables are real triangles too; do not demand a second roof feature.
    for porch in porches:
        if porch.get('roof') == 'gable':
            gables.append(porch)
        elif porch.get('roof') == 'mixed':
            gables.append({'slot': porch['slot'] + porch.get('gable_offset', 0),
                           'span': porch.get('gable_span', min(2, porch['span']))})
    for i, observed in enumerate(observations.get('roofs', [])):
        centre = observed['at'] + observed['width'] / 2
        cell = (1 - centre if spec['mirror'] else centre) * slot_count
        owner = next((u for u in spec['upper'] if u['slot'] <= cell < u['slot'] + u['span']), None)
        roof = owner['roof'] if owner else spec['blocks']['garage' if cell < 6 else 'main']['roof']
        if bool(owner) != (observed['story'] == 2):
            issues.append(f"Roof region {i + 1} has the wrong supporting story count; attic windows are not full stories.")
        if observed['ridge'] != 'unknown' and roof['ridge'] != observed['ridge']:
            issues.append(f"Roof region {i + 1} needs underlying ridge={observed['ridge']}, independent of its front gable.")
        if observed['front_gable'] == 'cross' and not any(
                r['kind'] == 'gable' and observed['at'] <= region(r)[0] + region(r)[1] / 2
                <= observed['at'] + observed['width'] for r in spec['roof']):
            issues.append(f"Roof region {i + 1} needs a projecting cross-gable on its underlying roof.")
    for i, observed in enumerate(observations['gables']):
        if not any(matches(g, observed) for g in gables):
            issues.append(f'Gable region {i + 1} has the wrong position or width.')
    return issues


def restore_missing_upper_windows(spec, observations, slot_count=18):
    """Recover a wholly omitted row only when one observed upper matches uniquely.

    Counts are image observations; evenly spaced positions are explicitly inferred.
    Partial rows and ambiguous/missing upper volumes remain review issues, not guesses.
    """
    notes = []
    if not observations:
        return notes
    matches = []
    for observed in observations['upper']:
        candidates = []
        for upper in spec['upper']:
            a, w = upper['slot'] / slot_count, upper['span'] / slot_count
            if spec['mirror']:
                a = 1 - a - w
            if abs(a - observed['at']) <= .13 and abs(w - observed['width']) <= .16:
                candidates.append(upper)
        matches.append(candidates)
    for observed, candidates in zip(observations['upper'], matches):
        if len(candidates) != 1:
            continue
        upper = candidates[0]
        if sum(any(u is upper for u in group) for group in matches) != 1:
            continue
        count = observed['windows']
        if not 0 < count <= upper['span']:
            continue
        if any(g.get('story') == 2 and g['slot'] < upper['slot'] + upper['span']
               and upper['slot'] < g['slot'] + g['span'] for g in spec['ground']):
            continue
        for i in range(count):
            spec['ground'].append({'kind': 'window', 'slot': upper['slot'] + int((i + .5) * upper['span'] / count),
                                   'span': 1, 'size': 'standard', 'shutters': False, 'story': 2})
        notes.append(f"Restored {count} omitted upstairs window groups at upper slot {upper['slot']} from photo observations; spacing inferred, review placement.")
    spec['ground'].sort(key=lambda g: (g['slot'], g.get('story', 1), g['kind']))
    return notes
