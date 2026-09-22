"""Small photo contracts; details cannot change the compiled architecture."""
import copy
import json

from services.house_photo_compiler import analysis_schema, compile_analysis, validate_analysis
from services.house_photo_schema import obj, arr, enum, TEXT

LAYERS = ('volumes', 'porches', 'gables', 'dormers')
CHECKS = ('wall_stories', 'roof_planes', 'front_widths', 'projections', 'porch_coverage')
STRUCTURE_PROMPT = '''Describe only the house's architecture in the supplied schema.
Image 1 establishes the FRONT and the single left-to-right 0..1 facade axis.
Other images show the SAME house: use them to resolve roof planes, depth and garage
entry, never transfer their image coordinates or side-facing features to the front.
Volumes are non-overlapping FRONT rectangular wall regions up to their eaves.
Count full wall stories below the eaves, NOT windows or attic triangles. Separate
one-story wings from a narrower two-story centre when the eave heights differ.
Each volume has an underlying roof: parallel is across the house front;
perpendicular is front-to-back. Read the roof planes behind visible triangles.
A front triangle can be a cross-gable on a parallel ridge or the end of a
perpendicular ridge. Porch gables belong to porches. Dormers belong to volumes.
Describe one continuous porch cover, including a small entrance gable separately.
Keep relative facade widths and forward/recessed wall relationships. An L-shaped
wing can have intersecting ridges: record its dominant underlying ridge and explain
the intersection in evidence/limitations. Do not invent another story to encode it.
Use unknown for unseen geometry. Garage side is house-front left/right; garage_entry
is front, side, or unknown. A hidden garage must not determine visible roof geometry.
IDs are unique; owners reference existing volumes or porches. Explain story and roof
decisions briefly in evidence, citing image numbers. No windows, doors, materials,
bounding boxes, renderer slots or configuration. Do not optimize for a particular style.
'''
DETAIL_PROMPT = '''Fill only openings, finish bands and palette for the supplied LOCKED
architecture. All positions use the primary photo's full FRONT facade axis, 0..1.
Other images clarify appearance, not front positions. Do not describe side-facing
windows or garage doors as front openings. Use only the supplied owner IDs.
Upper openings belong to two-story volumes; attic windows belong to gables.
Count framed units, not panes. Window count 1..4 is independent of occupied width:
one centred window or one group, with shutters only outside the group. Door count
must be 1 or 2; a double door is ONE opening with two mirrored leaves, shared trim
and lighting outside the assembly. Width covers the whole opening, not each leaf.
Keep separate upstairs windows separate.
Do not change stories, wall widths, projections, roofs, porches or garage orientation.
Use permitted material/color values, unknown when uncertain. Report unsupported
details briefly in limitations. Return the detail schema only.
'''


def structure_schema():
    base = analysis_schema(1)['properties']
    fields = {k: copy.deepcopy(base[k]) for k in
              ('viewpoint', 'garage_side', *LAYERS, 'limitations')}
    fields['schema_version'] = {'type': 'integer', 'enum': [3]}
    fields['garage_entry'] = enum(('front', 'side', 'unknown'))
    return obj(fields)


def detail_schema():
    base = analysis_schema(1)['properties']
    fields = {k: copy.deepcopy(base[k]) for k in ('openings', 'finishes', 'palette', 'limitations')}
    variants = []
    for kind in ('window', 'door', 'garage_door'):
        opening = copy.deepcopy(base['openings']['items'])
        opening['properties']['kind'] = enum((kind,))
        if kind == 'door':
            opening['properties']['count']['maximum'] = 2
        variants.append(opening)
    fields['openings'] = arr({'anyOf': variants})
    return obj(fields)


def review_schema():
    return obj({'structure': structure_schema(), 'reasons': arr(TEXT),
                'checks': obj({k: enum(('matched', 'corrected', 'uncertain')) for k in CHECKS})})


def as_analysis(structure):
    if not isinstance(structure, dict):
        raise ValueError('structure must be an object')
    allowed = set(structure_schema()['properties'])
    if set(structure) - allowed - {'_model'} or allowed - set(structure):
        raise ValueError('structure fields do not match the architectural contract')
    if structure['schema_version'] != 3 or structure['garage_entry'] not in ('front', 'side', 'unknown'):
        raise ValueError('invalid structure version or garage entry')
    a = {k: copy.deepcopy(structure[k]) for k in ('viewpoint', 'garage_side', *LAYERS, 'limitations')}
    a.update(schema_version=1, openings=[], finishes=[],
             palette={k: 'unknown' for k in ('roof', 'frame', 'door', 'trim')})
    # Let the existing compiler reconcile tiny adjacent-boundary rounding before
    # enforcing ownership and overlap rules; don't create a stricter second gate.
    errors = validate_analysis(a, _shape_only=True)
    if errors:
        raise ValueError('; '.join(errors[:6]))
    return a


def compile_structure(structure):
    spec, notes, trace = compile_analysis(as_analysis(structure), preserve_masses=True)
    # Entry is architectural evidence, never inferred from the detail inventory.
    spec['blocks']['garage']['orientation'] = 'front' if structure['garage_entry'] == 'front' else 'side'
    notes = [n for n in notes if 'colour unknown' not in n and 'canonical one' not in n]
    notes.append('Structure preview; windows and materials are added after the roof and story review.')
    spec['unexpressed'] = [n[:80] for n in notes[:8]]
    return spec, notes, trace


def geometry(spec):
    """Everything details must preserve; attic glazing and finishes are excluded."""
    def roof(r):
        return {k: v for k, v in r.items() if k not in ('window', 'cladding', 'body')}
    return {'mirror': spec['mirror'], 'pitch_deg': spec['pitch_deg'],
            'blocks': {k: {f: copy.deepcopy(v[f]) for f in ('depth', 'orientation') if f in v} |
                       {'roof': roof(v['roof'])} for k, v in spec['blocks'].items()},
            'upper': [{**u, 'roof': roof(u['roof'])} for u in spec['upper']],
            'masses': [{**m, 'roof': roof(m['roof'])} for m in spec.get('masses', [])],
            'roof': [roof(r) for r in spec['roof']],
            'porches': [copy.deepcopy(g) for g in spec['ground'] if g['kind'] == 'porch']}


def apply_details(structure, locked, details):
    if not isinstance(details, dict) or set(details) - set(detail_schema()['properties']) - {'_model'}:
        raise ValueError('detail response may contain only openings, finishes, palette and limitations')
    if set(detail_schema()['properties']) - set(details):
        raise ValueError('detail response is incomplete')
    a = as_analysis(structure)
    for k in ('openings', 'finishes', 'palette', 'limitations'):
        a[k] = copy.deepcopy(details[k])
    if isinstance(a['limitations'], list):
        a['limitations'] = copy.deepcopy(structure['limitations']) + a['limitations']
    errors = validate_analysis(a, _shape_only=True)
    if errors:
        raise ValueError('; '.join(errors[:6]))
    # Detail ownership cannot invalidate every other opening/material. Resolve
    # redundant attic ownership only within the explicitly named wall/porch.
    gables = {g['id']: g for g in a['gables']}
    parents = {r['id'] for layer in ('volumes', 'porches') for r in a[layer]}
    retained = []
    adjustments = []
    for opening in a['openings']:
        if opening['level'] == 'attic' and opening['owner'] in parents:
            matches = [g for g in gables.values() if g['owner'] == opening['owner']
                       and opening['at'] >= g['at'] - .02
                       and opening['at'] + opening['width'] <= g['at'] + g['width'] + .02]
            if len(matches) == 1 and opening['kind'] == 'window':
                opening['owner'] = matches[0]['id']
                adjustments.append(opening['id'] + ': attic window resolved to existing gable ' + opening['owner'] + '.')
            else:
                adjustments.append(opening['id'] + ': attic opening left unplaced; no unique existing gable matches its declared owner and position.')
                continue
        retained.append(opening)
    a['openings'] = retained
    a['limitations'] = adjustments + a['limitations']
    # The compiler's unknown-side heuristic also considers entry placement.
    # Freeze its chosen mapping before giving it any openings.
    a['garage_side'] = 'right' if locked['mirror'] else 'left'
    if structure['garage_entry'] != 'front' and isinstance(a['openings'], list):
        a['openings'] = [o for o in a['openings'] if not isinstance(o, dict) or o.get('kind') != 'garage_door']
    revised, notes, trace = compile_analysis(a, preserve_masses=True)
    trace['detail_ownership_adjustments'] = adjustments
    revised['blocks']['garage']['orientation'] = locked['blocks']['garage']['orientation']
    if geometry(revised) != geometry(locked):
        raise ValueError('detail compilation would change locked architecture; structure retained')
    return revised, notes, trace


def complete_photo(entry, context, call):
    """Review architecture once, then fill details; retry details without re-review."""
    trace = entry['photo_trace']
    reviewed = entry.get('reviewed_structure')
    if reviewed is None:
        response = call('structural_review', STRUCTURE_PROMPT +
            '\nThe LAST image is the rendered structure, not a reference. Compare its silhouette, '
            'eave heights, full wall stories, roof planes and porch footprint to the photos. '
            'Ignore missing windows/materials. Return corrected structure, concise image-based reasons, '
            'and matched/corrected/uncertain for every check. Keep supported geometry if uncertain. '
            'Compiler limitations are representation limits, not evidence that the photo has different architecture.',
            context + '\nInitial structure: ' + json.dumps(entry['structure'], separators=(',', ':')) +
            '\nCompiler limitations: ' + json.dumps(trace.get('compiler_notes', [])), review_schema(), True)
        reasons = response.get('reasons')
        checks = response.get('checks')
        if not isinstance(reasons, list) or not reasons or any(not isinstance(r, str) or not r.strip() for r in reasons):
            raise ValueError('structural review requires image-based reasons')
        if not isinstance(checks, dict) or set(checks) != set(CHECKS) or any(v not in ('matched', 'corrected', 'uncertain') for v in checks.values()):
            raise ValueError('structural review checks are incomplete')
        candidate, notes, compiled = compile_structure(response.get('structure'))
        trace.update(structural_review=copy.deepcopy(checks), review_analysis=copy.deepcopy(response['structure']),
                     review_compilation=compiled, review_notes=notes)
        if 'uncertain' in checks.values():
            # Preserve a useful original draft, and don't erase its detail inventory.
            structure = copy.deepcopy(entry['structure'])
            candidate = copy.deepcopy(entry['spec'])
            reasons = ['Roof/story review is uncertain; original architecture retained.'] + reasons
        else:
            structure = copy.deepcopy(response['structure'])
        reviewed = {'structure': structure, 'spec': candidate, 'reasons': reasons + notes}
        entry['reviewed_structure'] = copy.deepcopy(reviewed)
        trace['locked_structure'] = copy.deepcopy(structure)
        trace['locked_geometry'] = geometry(candidate)
    try:
        details = call('details', DETAIL_PROMPT, context + '\nLocked architecture: ' +
                       json.dumps(reviewed['structure'], separators=(',', ':')), detail_schema())
        revised, notes, compiled = apply_details(reviewed['structure'], reviewed['spec'], details)
        trace.update(detail_analysis=copy.deepcopy(details), detail_compilation=compiled,
                     detail_notes=notes, detail_geometry_preserved=True)
        reasons = [r for r in reviewed['reasons'] if not r.startswith('Structure preview;')] + notes
        return revised, list(dict.fromkeys(reasons)), False
    except Exception as ex:
        trace['detail_error'] = str(ex)
        return copy.deepcopy(reviewed['spec']), reviewed['reasons'] + [
            'Details unavailable; architecture retained. Compare to photo retries details. ' + str(ex)], True
