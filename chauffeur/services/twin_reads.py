"""Small, metered reads of cropped drawing sheets; no plan/world conversion."""
import json
import re

from services import llm, model_pools, storage, twin_cost, twin_place
from services.twin_draft import FINISHES_PROMPT


KINDS = ('sheet_roles', 'outline', 'walls', 'openings', 'rooms', 'registration',
         'roof', 'pitch', 'plot', 'site', 'finishes', 'photo_parts')
MAX_OUTPUT = {'sheet_roles': 2048, 'outline': 4096, 'walls': 16384,
              'openings': 16384, 'rooms': 16384, 'registration': 4096,
              'roof': 8192, 'pitch': 2048, 'plot': 8192, 'site': 8192,
              'finishes': 8192, 'photo_parts': 2048}

# Reuse P0's reading/JSON rules, but its world-coordinate rules do not apply.
_CROP_RULES = """
Coordinates are crop-normalised [u,v], origin top-left, u right and v down,
from 0 to 1 within the supplied cropped image, never page or world coordinates.
Boxes are [u0,v0,u1,v1]. Physical lengths are feet unless named thickness_in
(inches); roof pitch is rise per 12. Context supplies settled pieces and IDs.
The example numbers explain the schema; they are not evidence about this house.
Read only what the drawings show. For uncertain required fields, give the best
reading with lower confidence and explain the uncertainty in why when available,
rather than omitting required fields. Omit optional features that are absent.
Return only the requested JSON fragment, with no prose or Markdown.
"""
_DIMENSION_RULES = """
dimension.a and dimension.b (scale.a and scale.b for a plot) are the two endpoints
of the drawn dimension line in crop coordinates; feet is its stated length in
feet, not a coordinate or the distance between arbitrary footprint corners.
Architect notation: 70'-0" means 70.0 ft; 65'-4" means 65.333 ft;
150.20' means 150.2 ft. Convert inches to feet by dividing by 12.
"""
_FLOOR_RULES = """
Trace the footprint of enclosed walls only. Exclude open porches and decks
from outline and lower_outline; they may still be named as wings.
On a floor sheet, dashed lines show another floor and must never be traced as
this floor's outline. In registration, return the dashed lower floor as
lower_outline and the current upper floor as outline, both in this crop.
A wing is the tight bounding box of one projecting mass of this floor's
footprint, such as a garage or side wing. Boxes must not overlap more than
needed; the whole house is not a wing unless its footprint is a plain rectangle.
"""
_DIMENSION = '"dimension":{"a":[0.1,0.9],"b":[0.9,0.9],"feet":70.0}'
_OUTLINE = '"outline":[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]]'
_WINGS = '"wings":[{"name":"garage","box":[0.6,0.5,0.9,0.9]}]'
PROMPTS = {
    'sheet_roles': '''Sort drawing sheets by visible content. Mixed sheets may
have multiple entries for one page, with a crop box for each region. Page is
one-based; role is floor, roof, plot, survey, landscape, elevation or other;
level is a name or null; box is null for the full page. Context lists the
source's part and all parts of the place, and original page_numbers in image
order. Use those page numbers in the answer. Only when a page clearly shows
another listed part, include optional elsewhere with that part's id. Return
{"pages":[{"page":1,"role":"floor","level":"Main floor","box":null}]}.''',
    'outline': 'Read one floor footprint and a readable dimension to set scale. '
               'Trace the outline with at least three points; name visible wings. '
               + _DIMENSION_RULES + _FLOOR_RULES
               + 'Return {' + _DIMENSION + ',' + _OUTLINE + ',' + _WINGS
               + ',"confidence":0.8,"why":""}.',
    'walls': '''Read walls in the cropped region, using the settled outline in
context. Return {"walls":[{"from":[0.1,0.1],"to":[0.9,0.1],
"exterior":true,"thickness_in":6}],"confidence":0.8,"why":""}.''',
    'openings': '''Read visible openings. The engine snaps each opening to the
nearest settled wall; at is its crop-normalised centre, never a wall distance.
kind is window, door, slider, bifold, passage or garage. Sill and head are
heights above the floor. Return {"openings":[{"at":[0.3,0.1],"kind":"window",
"width_ft":3.0,"sill_ft":2.0,"head_ft":7.0}]}.''',
    'rooms': '''Read room boundaries with at least three polygon points. Use
visible names; leave an unreadable name blank. Return
{"rooms":[{"name":"","polygon":[[0.1,0.1],[0.5,0.1],[0.5,0.6]]}]}.''',
    'registration': 'Read this upper floor, its dimension and the lower-floor '
                    'outline visible on this sheet, using context to identify '
                    'the floors. Both outlines use this crop, not settled world '
                    'coordinates. ' + _DIMENSION_RULES + _FLOOR_RULES
                    + 'Return {' + _DIMENSION + ','
                    '"lower_outline":[[0.1,0.1],[0.9,0.1],[0.9,0.9]],'
                    + _OUTLINE + ',' + _WINGS + ',"confidence":0.8,"why":""}.',
    'roof': 'Read the footprint of enclosed walls beneath the roof and individual sections. '
            'The outline excludes open porches and decks; section boxes may include their roofs. '
            'Section kind is '
            "hip, gable or shed. ridge 'x' means the ridge line runs along x "
            "(image horizontal); ridge 'y' means it runs along y (image vertical). "
            'low_side is null except for shed, where it names the eave edge '
            'the shed slopes down toward: x0 = left edge of the section box, '
            'x1 = right edge, y0 = top edge, y1 = bottom edge in image terms. '
            'Return {' + _OUTLINE + ',"sections":['
            '{"kind":"hip","box":[0.1,0.1,0.9,0.9],"ridge":"x",'
            '"low_side":null}],"confidence":0.8}.',
    'pitch': '''Estimate pitches from photos for the section IDs in context.
Do not invent section IDs. Pitch is numeric rise per 12. Return
{"pitches":[{"section":"roof-3","pitch":8,"confidence":0.6,"why":""}]}.''',
    'plot': '''Read the plot's scale dimension, lot perimeter, buildings and
street edge. street_edge is two adjacent zero-based lot indices [i,j] naming
the lot edge along the street (the last and first vertices are adjacent too).
Identify it from street labels or the drawn road. The sheet may be rotated:
the street may be on the right edge, not the bottom. Obtain scale from a drawn
dimension or the printed scale, such as 1"=30'. When using a printed scale,
choose a measurable line segment in the crop as scale.a/b and derive its feet
from that scale, accounting for the drawing's printed size and scan resolution;
do not treat crop fractions as paper inches. Return
{"scale":{"a":[0.1,0.1],"b":[0.1,0.9],"feet":150.2},
"lot":[[0.1,0.1],[0.9,0.1],[0.9,0.9],[0.1,0.9]],"street_edge":[0,1],
"buildings":[{"name":"house","outline":[[0.3,0.3],[0.6,0.3],[0.6,0.6]]}],
"confidence":0.8}.''' + _DIMENSION_RULES,
    'site': '''Read only visible site features; omit absent features. Do not
invent planting or furnishings. Return {"pool":{"polygon":[[0.1,0.1],
[0.3,0.1],[0.3,0.4]],"depth_ft":5},"hardscape":[{"kind":"patio",
"polygon":[[0.4,0.1],[0.8,0.1],[0.8,0.5]]}],"fire_pit":{"at":[0.5,0.7],
"radius_ft":3},"retaining_walls":[{"from":[0.1,0.8],"to":[0.9,0.8],
"height_ft":2}]}.''',
}
PROMPTS = {kind: prompt + _CROP_RULES for kind, prompt in PROMPTS.items()}
PROMPTS['finishes'] = FINISHES_PROMPT
PROMPTS['photo_parts'] = '''Suggest which of the context parts each photo shows.
Use only part ids from context. Photo index is zero-based in the supplied images.
For buildings without drawings, suggest a shell only when visible evidence supports it.
Storeys is an integer from 1 to 4; roof is gable, hip, shed or flat; pitch is rise
per 12 from 0 to 24. Confidence is from 0 to 1. Explain uncertainty in why.
These are suggestions for a person to accept, never changes to their place. Return
{"photos":[{"index":0,"parts":["part-id"]}],"shells":[{"building":"part-id",
"storeys":1,"roof":"gable","pitch":6,"confidence":0.5,"why":""}]}.
'''


def _number(value):
    # Reject bool, non-finite JSON extensions and arbitrarily large integers.
    return type(value) in (int, float) and -1e308 <= value <= 1e308


class _Validator:
    def __init__(self):
        self.problems = []

    def bad(self, path, message):
        self.problems.append(f'{path}: {message}')

    def object(self, value, path):
        if not isinstance(value, dict):
            self.bad(path, 'expected an object')
            return None
        return value

    def point(self, value, path):
        if not isinstance(value, list) or len(value) != 2 or not all(map(_number, value)):
            self.bad(path, 'expected a numeric [u,v] point')
            return None
        if any(v < -0.05 or v > 1.05 for v in value):
            self.bad(path, 'point outside crop-normalised bounds')
            return None
        # Small rounding overshoots are tolerated, but output stays in 0..1.
        return [min(1, max(0, v)) for v in value]

    def box(self, value, path):
        if not isinstance(value, list) or len(value) != 4:
            self.bad(path, 'expected [u0,v0,u1,v1]')
            return None
        a, b = self.point(value[:2], path + '[:2]'), self.point(value[2:], path + '[2:]')
        if a is None or b is None:
            return None
        if a[0] >= b[0] or a[1] >= b[1]:
            self.bad(path, 'box must have positive width and height')
            return None
        return a + b

    def polygon(self, value, path):
        if not isinstance(value, list):
            self.bad(path, 'expected a polygon list with at least 3 points')
            return None
        points = [self.point(p, f'{path}[{i}]') for i, p in enumerate(value)]
        points = [p for p in points if p is not None]
        if len(points) < 3:
            self.bad(path, 'outline/polygon needs at least 3 points')
            return None
        return points

    def numeric(self, value, path, *, minimum=0, positive=False, maximum=None):
        if (not _number(value) or value < minimum or (positive and value <= 0)
                or (maximum is not None and value > maximum)):
            self.bad(path, 'expected a finite number in range')
            return None
        return value

    def text(self, value, path):
        if not isinstance(value, str):
            self.bad(path, 'expected a string')
            return None
        return value

    def choice(self, value, path, choices):
        if value not in choices:
            self.bad(path, f'unknown value {value!r}')
            return None
        return value

    def dimension(self, value, path):
        value = self.object(value, path)
        if value is None:
            return None
        a, b = self.point(value.get('a'), path + '.a'), self.point(value.get('b'), path + '.b')
        feet = self.numeric(value.get('feet'), path + '.feet', positive=True)
        if a is None or b is None or feet is None:
            return None
        if a == b:
            self.bad(path, 'dimension endpoints are coincident')
            return None
        return {'a': a, 'b': b, 'feet': feet}

    def fields(self, value, path, required, optional=None):
        value = self.object(value, path)
        if value is None:
            return None
        out = {}
        valid = True
        for name, validate in required.items():
            parsed = validate(value.get(name), path + '.' + name)
            if parsed is None:
                valid = False
            else:
                out[name] = parsed
        for name, validate in (optional or {}).items():
            if name in value:
                parsed = validate(value[name], path + '.' + name)
                if parsed is not None:
                    out[name] = parsed
        return out if valid else None

    def items(self, value, path, validate):
        if not isinstance(value, list):
            self.bad(path, 'expected a list')
            return None
        out = []
        for i, item in enumerate(value):
            parsed = validate(item, f'{path}[{i}]')
            if parsed is not None:
                out.append(parsed)
        return out


def parse(kind, answer):
    """Validate a JSON value without I/O or input mutation; drop invalid pieces.

    Problems name the affected field/index. Missing/invalid top-level fields are
    omitted; an explicitly supplied list remains a list even if all items fail.
    """
    v = _Validator()
    if not isinstance(kind, str) or kind not in KINDS:
        return {}, ['kind: unknown read kind']
    if v.object(answer, kind) is None:
        return {}, v.problems

    positive = lambda value, path: v.numeric(value, path, positive=True)
    confidence = lambda value, path: v.numeric(value, path, maximum=1)
    nullable_text = lambda value, path: '' if value is None else v.text(value, path)
    wing = lambda value, path: v.fields(value, path, {'name': v.text, 'box': v.box})
    segment = {'from': v.point, 'to': v.point}

    def nullable_box(value, path):
        return None if value is None else v.box(value, path)

    def page(value, path):
        if v.object(value, path) is None:
            return None
        before = len(v.problems)
        number = value.get('page')
        if type(number) is not int or number < 1:
            v.bad(path + '.page', 'expected a positive page integer')
        role = v.choice(value.get('role'), path + '.role',
                        ('floor', 'roof', 'plot', 'survey', 'landscape', 'elevation', 'other'))
        level = nullable_text(value.get('level'), path + '.level')
        box = nullable_box(value.get('box'), path + '.box')
        if len(v.problems) != before:
            return None
        out = {'page': number, 'role': role, 'level': None if value.get('level') is None else level, 'box': box}
        if value.get('elsewhere') is not None:
            elsewhere = v.text(value['elsewhere'], path + '.elsewhere')
            if elsewhere is not None:
                out['elsewhere'] = elsewhere
        return out

    def wall(value, path):
        def boolean(value, path):
            if type(value) is not bool:
                v.bad(path, 'expected a boolean')
                return None
            return value
        return v.fields(value, path, {**segment, 'exterior': boolean}, {'thickness_in': positive})

    def section(value, path):
        out = v.fields(value, path, {
            'kind': lambda x, p: v.choice(x, p, ('hip', 'gable', 'shed')),
            'box': v.box, 'ridge': lambda x, p: v.choice(x, p, ('x', 'y'))})
        if out is None:
            return None
        low = value.get('low_side')
        if low is not None and v.choice(low, path + '.low_side', ('x0', 'x1', 'y0', 'y1')) is None:
            return None
        out['low_side'] = low
        return out

    def materials(value, path):
        if v.object(value, path) is None:
            return None
        out = {}
        for role, material in value.items():
            if not isinstance(role, str):
                v.bad(path, 'material role must be a string')
                continue
            parsed = v.fields(material, path + '.' + role, {'id': v.text}, {'color': v.text})
            if parsed is not None:
                if 'color' in parsed and not re.fullmatch(r'#[0-9a-fA-F]{6}', parsed['color']):
                    v.bad(path + '.' + role + '.color', 'expected #rrggbb')
                    del parsed['color']
                out[role] = parsed
        return out

    def photo(value, path):
        def index(value, path):
            if type(value) is not int or value < 0:
                v.bad(path, 'expected a nonnegative photo index')
                return None
            return value

        return v.fields(value, path, {'index': index, 'parts': lambda x, p: v.items(x, p, v.text)})

    def shell(value, path):
        out = v.fields(value, path, {'building': v.text, 'storeys': v.numeric,
                                    'roof': v.text, 'pitch': v.numeric,
                                    'confidence': confidence, 'why': v.text})
        if out is not None:
            try:
                checked = twin_place.check_shell(out)
            except ValueError as exc:
                v.bad(path, str(exc))
                return None
            out['pitch'] = checked['pitch']
        return out

    lists = {
        'photos': photo, 'shells': shell,
        'pages': page,
        'wings': wing,
        'walls': wall,
        'openings': lambda x, p: v.fields(x, p, {
            'at': v.point, 'kind': lambda x, p: v.choice(x, p, ('window', 'door', 'slider', 'bifold', 'passage', 'garage')),
            'width_ft': positive, 'sill_ft': v.numeric, 'head_ft': positive}),
        'rooms': lambda x, p: v.fields(x, p, {'name': v.text, 'polygon': v.polygon}),
        'sections': section,
        # A reader may echo the section context object instead of just its id.
        'pitches': lambda x, p: v.fields(x, p, {'section': lambda x, p: v.text(x.get('id') if isinstance(x, dict) else x, p), 'pitch': v.numeric},
                                        {'confidence': confidence, 'why': v.text}),
        'buildings': lambda x, p: v.fields(x, p, {'name': v.text, 'outline': v.polygon}),
        'hardscape': lambda x, p: v.fields(x, p, {'kind': v.text, 'polygon': v.polygon}),
        'retaining_walls': lambda x, p: v.fields(x, p, {**segment, 'height_ft': positive}),
    }
    fields = {
        'sheet_roles': ('pages',),
        'outline': ('dimension', 'outline', 'wings'),
        'walls': ('walls',), 'openings': ('openings',), 'rooms': ('rooms',),
        'registration': ('dimension', 'lower_outline', 'outline', 'wings'),
        'roof': ('outline', 'sections'), 'pitch': ('pitches',),
        'plot': ('scale', 'lot', 'street_edge', 'buildings'),
        'site': ('pool', 'hardscape', 'fire_pit', 'retaining_walls'),
        'finishes': ('materials',),
        'photo_parts': ('photos', 'shells'),
    }[kind]
    out = {}
    for name in fields:
        path = kind + '.' + name
        if name not in answer:
            # Wings and individual site features are optional.
            if name != 'wings' and kind != 'site' and not (kind == 'registration' and name == 'lower_outline'):
                v.bad(path, 'missing field')
            continue
        value = answer[name]
        if name in lists:
            parsed = v.items(value, path, lists[name])
        elif name in ('dimension', 'scale'):
            parsed = v.dimension(value, path)
        elif name in ('outline', 'lower_outline', 'lot'):
            parsed = v.polygon(value, path)
        elif name == 'materials':
            parsed = materials(value, path)
        elif name == 'pool':
            parsed = v.fields(value, path, {'polygon': v.polygon}, {'depth_ft': positive})
        elif name == 'fire_pit':
            parsed = v.fields(value, path, {'at': v.point, 'radius_ft': positive})
        else:  # Clamping keeps indices; dropping a vertex shifts them.
            parsed = None
            lot = answer.get('lot')
            if (isinstance(value, list) and len(value) == 2 and isinstance(lot, list)
                    and all(type(i) is int and 0 <= i < len(lot) for i in value)
                    and value[0] != value[1] and len(out.get('lot', [])) == len(lot)):
                parsed = list(value)
            else:
                v.bad(path, 'expected two distinct indices into a lot with no dropped vertices')
        if parsed is not None:
            out[name] = parsed
    for name, validate in (('confidence', confidence), ('why', v.text)):
        if name in answer:
            parsed = validate(answer[name], kind + '.' + name)
            if parsed is not None:
                out[name] = parsed
    return out, v.problems


def _usable(kind, fragment, problems):
    if kind in ('outline', 'registration'):
        return bool(fragment.get('outline')) and bool(fragment.get('dimension'))
    if kind == 'roof':
        return bool(fragment.get('outline')) and bool(fragment.get('sections'))
    if kind == 'plot':
        return bool(fragment.get('lot')) and bool(fragment.get('scale'))
    # Explicit empty collections can faithfully describe an absent feature.
    keys = {'sheet_roles': ('pages',), 'walls': ('walls',), 'openings': ('openings',),
            'rooms': ('rooms',), 'pitch': ('pitches',), 'finishes': ('materials',),
            'photo_parts': ('photos', 'shells'),
            'site': ('pool', 'hardscape', 'fire_pit', 'retaining_walls')}[kind]
    return any(key in fragment and (fragment[key] or not problems) for key in keys)


def read(kind, images, context, *, run, step):
    """Meter every request; retry a token-truncated reply once at twice the cap."""
    if not isinstance(kind, str) or kind not in KINDS:
        return {'error': 'Unknown twin read kind.'}
    try:
        settings = storage.get_settings()
        _, key = model_pools.credentials('twin', settings)
    except twin_cost.CheckpointReached:
        raise
    except Exception as exc:
        return {'error': str(exc)}
    if not key:
        return {'error': 'No model key is configured for twin reads.'}
    try:
        user_prompt = json.dumps({'step': step, 'context': context}, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        return {'error': str(exc)}
    for attempt in range(2):
        usage, provider_usage = [], []
        twin_cost.require_clear()
        try:
            # HTTP-attempt rows preserve refusal status; keep the compatibility
            # fallback for mocked/older providers. Each attempt is charged once.
            with llm.collect_usage() as provider_usage:
                answer = model_pools.call_pool_json(
                    'twin', key, PROMPTS[kind], user_prompt, images=images,
                    strict_json=True, max_models=1, thinking_level='low',
                    max_output_tokens=MAX_OUTPUT[kind] * (attempt + 1), timeout_s=120,
                    usage=usage, settings=settings)
        except twin_cost.CheckpointReached:
            raise
        except Exception as exc:
            answer = {'error': str(exc)}
        finally:
            twin_cost.record(f'step:{kind}', provider_usage or usage, run)
        error = str(answer.get('error', '')) if isinstance(answer, dict) else ''
        if attempt or not re.search(r'(?:finish\s*=\s*[\"\']?max_tokens\b|reason\s*=\s*max_output_tokens\b)',
                                    error, re.IGNORECASE):
            break
    if isinstance(answer, dict) and 'error' in answer:
        return {'error': str(answer['error'])}
    fragment, problems = parse(kind, answer)
    if not _usable(kind, fragment, problems):
        return {'error': '; '.join(problems) or f'{kind} returned no usable fragment.'}
    if problems:
        fragment['problems'] = problems
    return fragment
