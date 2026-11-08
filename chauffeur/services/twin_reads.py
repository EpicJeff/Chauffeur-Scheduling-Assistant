"""Metered crop reads and whole-building reads in dimensioned building feet."""
import json
import re

from services import llm, model_pools, storage, twin_cost, twin_place
from services.twin_draft import FINISHES_PROMPT


KINDS = ('sheet_roles', 'outline', 'walls', 'openings', 'rooms', 'registration',
         'roof', 'pitch', 'plot', 'site', 'finishes', 'photo_parts',
         'draft', 'draft_level', 'draft_rooms')
MAX_OUTPUT = {'sheet_roles': 2048, 'outline': 4096, 'walls': 16384,
              'openings': 16384, 'rooms': 16384, 'registration': 4096,
              'roof': 8192, 'pitch': 2048, 'plot': 8192, 'site': 8192,
              'finishes': 8192, 'photo_parts': 2048,
              'draft': 64000, 'draft_level': 32000, 'draft_rooms': 32000}
THINKING = {'draft': 'medium', 'draft_level': 'medium', 'draft_rooms': 'medium'}
TIMEOUT = {'draft': 420, 'draft_level': 300, 'draft_rooms': 300}
OUTPUT_CAP = {'anthropic': 64000, 'openai': 64000, 'gemini': 65536}

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

# These rules use the successful whole-set spike's dimensioned frame, never
# _CROP_RULES. Keep the same geometry rules in the per-level fallback.
_DRAFT_RULES = '''
UNITS AND MEASURING
- Work in decimal feet from the PRINTED DIMENSION STRINGS (31'-0" = 31.0,
  5'-8" = 5.667, 4" = 0.333). Chain partial strings against the overall string
  beside them; report strings that do not add up in checks and notes.
- Never take a position from pixel distances when a dimension string or a size
  callout gives it. Only an element with no dimension may be scaled from the
  nearest dimension strings; name every scaled element in notes.
- Size callouts are width x height: 2^8 x 5^2 means 2'-8" by 5'-2";
  12^0 x 8^0 SLIDER means 12'-0" wide by 8'-0" tall.
- Sheet notes (CLG. HGT., SET WINDOWS @ ... for head height, door height,
  PLATE HGT., knee walls), elevations and building sections when present are
  the sources for heights. When a height is missing, use a typical value
  checked against the photos, and list each assumed height in notes.

ONE FRAME FOR THE WHOLE BUILDING
- Origin (0,0) is the front-left corner of the OVERALL dimension box of the
  enclosed ground floor: x=0 at the leftmost exterior wall face, y=0 at the
  frontmost face as seen standing in front. It need not be a wall corner.
  +x runs right along the front; +y runs toward the rear. Match the front photo
  by entry door, porch and gables. Plans may put the front at the bottom of the
  sheet, so +y then runs UP the sheet.
- Every level uses this same frame. Place upper levels using strings shared
  with the floor below, aligned wall lines and the stair. State in checks which
  strings fixed each upper level's x and y offsets.
- Keep each staggered wing's own front and rear y from side and partial strings;
  only the frontmost wall lies at y=0. A porch sits in front of its own wall.
  List every wing's front and rear y and the strings used in checks.wing_y.
- Overall dimensions are to the outside wall face. Outline points and exterior
  wall endpoints lie on that face.

LEVELS AND WALLS
- levels: [{id, name, elevation, ceiling, outline:[[x,y],...]}]. Use L1, L2, ...
  in elevation order; use the page's level name from context as name. L1 is at
  elevation 0, top of slab. Each upper elevation includes the floor framing
  depth from the section; ceiling is the level's ceiling height from the notes.
- Outline traces ENCLOSED walls only, with at least three corners, without
  repeating the first point. Open porches and decks are never in an outline.
  A screened porch is an open porch with a roof, not an enclosed room.
- A storey-and-a-half area with rooms under the roof is still a level with
  half: true and an outline of the floor area inside the knee walls. Give it a
  floor even if no full-height exterior walls surround it. Knee walls have
  exterior: false and their own height; the roof above remains the roof.
- walls: [{id, level, from:[x,y], to:[x,y], height, thickness, exterior}]. All
  lengths, including thickness, are feet. Exterior walls follow the outline
  exactly, share endpoints exactly and close it. Height is above its own floor.
- GABLE ENDS apply only to gable sections, never hips. Do not write an upper
  wall along a gable end when the section's plate is below the top of that
  upper wall: the roof generator supplies the triangle from plate to ridge.
  Under hips, and under gables with plate on the upper floor's own plate, write
  every upper exterior wall so the floor closes. Rooms under a low gable are
  bounded by knee walls and the gable ends themselves.

OPENINGS
- openings: [{id, wall, kind, at, width, sill, head}]. kind is window, door,
  slider, bifold, passage or garage. at is the distance in feet from the wall's
  from point to the opening's CENTRE. Sill and head are above its level's floor;
  head never exceeds wall height. Doors and sliders have sill 0. Use size
  callouts and head notes; include openings visible in elevations too.
- A gable opening is {id, gable:"front"|"rear", section, kind, x, width, sill,
  head} for ridge "y": x is the centre along the building x axis, front is the
  y0 end, rear the y1 end. For ridge "x", give y instead of x: y is the centre
  along the building y axis, front is the x0 end, rear the x1 end. Gable sill
  and head are measured above the section's PLATE, not the level's floor.

ROOF
- roof: {sections:[...], extensions:[...]}. Each section is {id, kind, rect,
  ridge, low_side, pitch, plate, overhang}; kind is gable, hip, shed or flat.
  rect=[x0,y0,x1,y1] follows the bearing wall lines, excluding overhang; give
  overhang separately in feet. ridge is the axis the ridge LINE runs along:
  x runs side to side with gable ends left/right; y runs front to rear. A shed's
  low_side is its lowest rect edge: x0, x1, y0 or y1. Pitch is rise per 12;
  plate is the rafters' bearing elevation above the L1 floor.
- One section per roof mass: each storey block, wing, cross gable, porch roof
  and lean-to. Sections may overlap; their HIGHEST surface wins. Run lower
  wings into the taller roof's footprint toward its ridge/wall so valleys form.
  A cross gable on a hip is its own section, spanning its width into the hip.
- Read roof plans: solid outer lines are eaves; dashed lines are bearing walls
  and give rects; heavy/double lines are ridges; diagonals from outside corners
  to ridge ends are hips; diagonals from inside corners are valleys. A ridge
  ending at an eave in a gable bracket/triangle is a gable end; a ridge whose
  ends split into two hips is a hip. Read ridge axis from the ridge line itself.
- Give each section its own plate: a one-storey wing on its own plate, a taller
  block on the upper elevation plus upper plate height. Use pitches:{x0,x1,y0,y1}
  when slopes differ. If no pitch is drawn, estimate against photos, set
  pitch_source:"photos" and say so in notes. Check each ridge height against
  photos: plate + half span * pitch/12 for hips and gables.
- A small bracketed roof is an extension: {kind:"awning", section, wall, x0,
  x1, depth, pitch, eave, brackets}. Reference its section and supporting wall;
  it hangs from that exterior wall and slopes down away. depth is projection,
  eave is its low edge height above L1. brackets is an integer count, 0 if none,
  never true/false. It need not hang from the section's front edge.

PORCH, STAIRS AND PHOTOS
- porches: [{id, polygon, floor, columns:[{at:[x,y],size}], screened}] for
  EVERY front, rear and side porch, open or screened; floor 0 for a slab porch.
  Put columns at every drawn post, with size in feet; screened is a boolean.
- stairs: [{id, level, from:[x,y], to:[x,y], width, risers, rise_to}]. from is
  the bottom, to the top, level the starting level, rise_to the reached elevation.
- Photos confirm the front, roof forms and look. Never take a dimension from
  a photo. Example numbers explain the schema, never this building's dimensions.
- When a drawing is ambiguous, prefer the reading where walls, floors and roofs meet.

PAGE REGISTRATIONS AND CHECKS
- Request pages: [{image, level, anchors:[{px:[u,v], at:[x,y]}]}], one per floor
  page and the roof page. Use the supplied image index and level id. Give 3-4
  outline corners per page: u and v are fractions of that supplied image,
  origin top-left, u right, v down, in [0,1]; at is the same corner in building
  feet. These anchors align the sheet only; geometry still uses dimensions.
- checks: {front_edge, level_sizes:{L1:[width,depth]}, upper_offsets:{L2:
  "which strings placed it"}, wing_y:[{wing,front,rear,strings}]}.
- notes lists assumed heights/pitches, scaled elements and strings that disagree.
'''
_DRAFT_OUTPUT = '''
Write compact JSON, numbers to at most 2 decimals. The first character is {
and the last is }. No code fences or text before or after.
'''
PROMPTS['draft'] = '''Read the complete architectural set for ONE building as
one 3D plan in feet. All relevant sheets and photos are attached: read them
together, including elevations and sections when present. Write exterior walls
and knee walls only, no interior partitions, and rooms: []. Return
{building:{id,name,position:[0,0],rotation:0,base:0,levels,walls,openings,rooms,
roof:{sections,extensions},porches,stairs},pages,checks,notes}.
''' + _DRAFT_RULES + '''
Your whole reply, reasoning included, must fit in 64000 tokens: stop reasoning
by about 45000 and leave the rest for the JSON.
''' + _DRAFT_OUTPUT
PROMPTS['draft_level'] = '''Read ONLY the requested level, or ONLY the roof
when context requests the roof. Settled lower levels in context fix the frame
and dimensions; preserve them and their ids. Use shared dimension strings to
place the requested level in that same frame; never restart at a local origin.
Return {building:{levels,walls,openings,rooms:[],porches,stairs},pages,checks,notes}
restricted to that one level (exterior and knee walls only, no partitions).
For a roof-only request return {building:{roof:{sections,extensions},openings,porches},
pages,checks,notes}, with only roof and gable openings, given all settled levels.
Omit geometry outside the requested scope; never repeat or revise settled levels.
''' + _DRAFT_RULES + '''
Your whole reply, reasoning included, must fit in 32000 tokens: stop reasoning
by about 20000 and leave the rest for the JSON.
''' + _DRAFT_OUTPUT
PROMPTS['draft_rooms'] = '''Read room boundaries and INTERIOR walls from the
floor pages, given the settled building (levels, exterior walls and openings)
in context. Keep its level ids, outlines and shared coordinate frame exactly.
Return only {rooms:[{name,level,polygon:[[x,y],...]}],walls:[{id,level,
from:[x,y],to:[x,y],height,thickness,exterior:false}]} in building feet.
Use printed room labels; leave an unreadable name blank. Trace each room inside
its level's outline, without overlapping other rooms, covering the enclosed
floor area. Include interior partitions and knee walls, no exterior walls.
Do not return or revise levels, exterior openings, roofs, porches or stairs.
Measure in decimal feet from PRINTED DIMENSION STRINGS. Chain partial strings
against the overall dimensions; use nearby strings to scale only undimensioned
boundaries. Never use pixel distances when a dimension gives the position.
Keep the settled building's origin: +x runs right along the front, +y toward
the rear. Upper floors keep their settled offsets; do not use a local origin.
Wall height is above its own floor and thickness is in feet. Read ceiling and
knee-wall heights from sheet notes and sections; use a typical height only
when none is given. Wall endpoints should meet adjoining walls exactly.
Rooms use at least three polygon corners, without repeating the first point.
The walls key is optional when there are no interior walls to return.
Your whole reply, reasoning included, must fit in 32000 tokens: stop reasoning
by about 20000 and leave the rest for the JSON.
''' + _DRAFT_OUTPUT


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


def _parse_draft(kind, answer, v):
    """Check world-coordinate shapes; settling/normalize owns geometric gates.

    Partial level/roof reads may reference pieces in the settled context, so
    references are retained here rather than checked against this reply alone.
    """
    signed = lambda x, p: v.numeric(x, p, minimum=-1e308)
    positive = lambda x, p: v.numeric(x, p, positive=True)

    def boolean(value, path):
        if type(value) is not bool:
            v.bad(path, 'expected a boolean')
            return None
        return value

    def integer(value, path):
        if type(value) is not int or value < 0:
            v.bad(path, 'expected a nonnegative integer')
            return None
        return value

    def point(value, path):
        if not isinstance(value, list) or len(value) != 2 or not all(map(_number, value)):
            v.bad(path, 'expected a finite [x,y] point in feet')
            return None
        return list(value)

    def polygon(value, path):
        points = v.items(value, path, point)
        if points is None:
            return None
        if len(points) < 3 or len(points) != len(value):
            v.bad(path, 'polygon needs at least three valid points')
            return None
        return points

    def rect(value, path):
        if (not isinstance(value, list) or len(value) != 4 or not all(map(_number, value))
                or value[0] >= value[2] or value[1] >= value[3]):
            v.bad(path, 'expected a finite [x0,y0,x1,y1] with positive size')
            return None
        return list(value)

    def level(value, path):
        return v.fields(value, path, {'id': v.text, 'name': v.text, 'elevation': signed,
                                     'ceiling': positive, 'outline': polygon}, {'half': boolean})

    def wall(value, path):
        out = v.fields(value, path, {'level': v.text, 'from': point, 'to': point,
                                    'height': positive, 'thickness': positive, 'exterior': boolean},
                       {'id': v.text})
        if out is not None and kind == 'draft_rooms' and out['exterior']:
            v.bad(path + '.exterior', 'rooms read may only return interior walls')
            return None
        return out

    def opening(value, path):
        out = v.fields(value, path, {
            'kind': lambda x, p: v.choice(x, p, ('window', 'door', 'slider', 'bifold', 'passage', 'garage')),
            'width': positive, 'sill': v.numeric, 'head': positive}, {'id': v.text})
        if out is None:
            return None
        if ('wall' in value) == ('gable' in value):
            v.bad(path, 'reference exactly one wall or gable')
            return None
        if 'wall' in value:
            reference = v.fields(value, path, {'wall': v.text, 'at': v.numeric})
        else:
            if ('x' in value) == ('y' in value):
                v.bad(path, 'gable opening needs exactly one centre axis, x or y')
                return None
            axis = 'x' if 'x' in value else 'y'
            reference = v.fields(value, path, {
                'gable': lambda x, p: v.choice(x, p, ('front', 'rear')),
                'section': v.text, axis: signed})
        return {**out, **reference} if reference is not None else None

    def section(value, path):
        out = v.fields(value, path, {
            'id': v.text, 'kind': lambda x, p: v.choice(x, p, ('gable', 'hip', 'shed', 'flat')),
            'rect': rect, 'pitch': lambda x, p: v.numeric(x, p, maximum=24),
            'plate': signed, 'overhang': v.numeric}, {
            'pitch_source': lambda x, p: v.choice(x, p, ('drawn', 'photos', 'person', 'card', 'default')),
            'pitches': lambda x, p: v.fields(x, p, {}, {
                side: lambda x, p: v.numeric(x, p, maximum=24) for side in ('x0', 'x1', 'y0', 'y1')})})
        if out is None:
            return None
        if out['kind'] in ('gable', 'hip'):
            extra = v.fields(value, path, {'ridge': lambda x, p: v.choice(x, p, ('x', 'y'))})
        elif out['kind'] == 'shed':
            extra = v.fields(value, path, {
                'low_side': lambda x, p: v.choice(x, p, ('x0', 'x1', 'y0', 'y1'))})
        else:
            extra = {}
        return {**out, **extra} if extra is not None else None

    def extension(value, path):
        if v.object(value, path) is None:
            return None
        if value.get('kind') == 'awning':
            fields = {'x0': signed, 'x1': signed, 'depth': positive,
                      'eave': signed, 'brackets': integer}
        elif value.get('kind') == 'shed_continuation':
            fields = {'to_x': signed}
        else:
            v.bad(path + '.kind', 'unknown roof extension')
            return None
        return v.fields(value, path, {'kind': v.text, 'section': v.text, 'pitch': positive, **fields},
                        {'id': v.text, 'wall': v.text, 'overhang': v.numeric})

    room = lambda x, p: v.fields(x, p, {'name': v.text, 'level': v.text, 'polygon': polygon}, {'id': v.text})
    stair = lambda x, p: v.fields(x, p, {
        'level': v.text, 'from': point, 'to': point, 'width': positive,
        'risers': positive, 'rise_to': signed}, {'id': v.text})
    roof = lambda x, p: v.fields(x, p, {
        'sections': lambda x, p: v.items(x, p, section)}, {
        'extensions': lambda x, p: v.items(x, p, extension)})

    def porch(value, path):
        return v.fields(value, path, {'polygon': polygon}, {
            'id': v.text, 'screened': boolean,
            'floor': signed, 'columns': lambda x, p: v.items(x, p, lambda x, p: v.fields(
                x, p, {'at': point, 'size': positive}))})

    def anchor(value, path):
        def fraction_point(value, path):
            if (not isinstance(value, list) or len(value) != 2
                    or not all(_number(x) and 0 <= x <= 1 for x in value)):
                v.bad(path, 'expected image fractions [u,v] in 0..1')
                return None
            return list(value)
        return v.fields(value, path, {'px': fraction_point, 'at': point})

    def page(value, path):
        out = v.fields(value, path, {'image': integer, 'level': v.text,
                                    'anchors': lambda x, p: v.items(x, p, anchor)})
        if out is not None and len(out['anchors']) < 2:
            v.bad(path + '.anchors', 'at least two valid anchors are needed')
            return None
        return out

    if kind == 'draft_rooms':
        out = v.fields(answer, kind, {'rooms': lambda x, p: v.items(x, p, room)},
                       {'walls': lambda x, p: v.items(x, p, wall)}) or {}
        out.setdefault('walls', [])
        return out

    building_fields = {
        'levels': lambda x, p: v.items(x, p, level),
        'walls': lambda x, p: v.items(x, p, wall),
        'openings': lambda x, p: v.items(x, p, opening),
        'rooms': lambda x, p: v.items(x, p, room), 'roof': roof,
        'porch': lambda x, p: None if x is None else porch(x, p),
        'porches': lambda x, p: v.items(x, p, porch),
        'stairs': lambda x, p: v.items(x, p, stair),
    }
    building = v.object(answer.get('building'), kind + '.building')
    out = {'pages': v.items(answer.get('pages', []), kind + '.pages', page) or []}
    if building is not None:
        checked = v.fields(building, kind + '.building', {}, {
            **building_fields, 'id': v.text, 'name': v.text, 'position': point,
            'rotation': signed, 'base': signed})
        if building.get('porch') is None and 'porch' in building:
            # Null explicitly describes an absent optional porch.
            checked['porch'] = None
        if kind == 'draft':
            for name in ('levels', 'walls', 'openings', 'rooms', 'roof', 'stairs'):
                if name not in building:
                    v.bad(kind + '.building.' + name, 'missing field')
        elif len(checked.get('levels', [])) > 1:
            v.bad(kind + '.building.levels', 'per-level read must contain only one level')
            checked['levels'] = []
        out['building'] = checked
    for name, validate in (('checks', v.object), ('notes', lambda x, p: v.items(x, p, v.text))):
        if name in answer:
            parsed = validate(answer[name], kind + '.' + name)
            if parsed is not None:
                # Do not share mutable checks with the caller's answer.
                out[name] = json.loads(json.dumps(parsed))
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
    if kind in THINKING:
        return _parse_draft(kind, answer, v), v.problems

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
    if kind in ('draft', 'draft_level'):
        building = fragment.get('building', {})
        return bool(building.get('levels')) or (
            kind == 'draft_level' and bool(building.get('roof', {}).get('sections')))
    if kind == 'draft_rooms':
        return any(key in fragment and (fragment[key] or not problems) for key in ('rooms', 'walls'))
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


def read(kind, images, context, *, run, step, checkpoint_checked=False):
    """Meter every request; only legacy crop reads retry a truncated reply.

    A paired draft's caller may check the checkpoint once for both reads.
    """
    if not isinstance(kind, str) or kind not in KINDS:
        return {'error': 'Unknown twin read kind.'}
    try:
        settings = storage.get_settings()
        model, key = model_pools.credentials('twin', settings)
    except twin_cost.CheckpointReached:
        raise
    except Exception as exc:
        return {'error': str(exc)}
    if not key:
        return {'error': 'No model key is configured for twin reads.'}
    draft = kind in THINKING
    output_limit = MAX_OUTPUT[kind]
    if draft:
        provider, _ = model_pools.split_model(model)
        cap = OUTPUT_CAP.get(provider, 0)
        if cap <= 0 or (kind == 'draft' and cap < 32000):
            return {'error': 'too small', 'truncated': True}
        output_limit = min(output_limit, cap)
    try:
        user_prompt = json.dumps({'step': step, 'context': context}, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, OverflowError) as exc:
        return {'error': str(exc)}
    truncated = False
    for attempt in range(1 if draft else 2):
        usage, provider_usage = [], []
        if not checkpoint_checked:
            twin_cost.require_clear()
        try:
            # HTTP-attempt rows preserve refusal status; keep the compatibility
            # fallback for mocked/older providers. Each attempt is charged once.
            with llm.collect_usage() as provider_usage:
                answer = model_pools.call_pool_json(
                    'twin', key, PROMPTS[kind], user_prompt, images=images,
                    strict_json='lenient' if draft else True, max_models=1,
                    thinking_level=THINKING.get(kind, 'low'),
                    max_output_tokens=output_limit * (attempt + 1), timeout_s=TIMEOUT.get(kind, 120),
                    usage=usage, settings=settings)
        except twin_cost.CheckpointReached:
            raise
        except Exception as exc:
            answer = {'error': str(exc)}
        finally:
            twin_cost.record(f'step:{kind}', provider_usage or usage, run)
        error = str(answer.get('error', '')) if isinstance(answer, dict) else ''
        truncated = bool(re.search(r'(?:finish\s*=\s*[\"\']?max_tokens\b|reason\s*=\s*max_output_tokens\b)',
                                   error, re.IGNORECASE))
        if draft or attempt or not truncated:
            break
    if isinstance(answer, dict) and 'error' in answer:
        return {'error': str(answer['error']), **({'truncated': True} if draft and truncated else {})}
    fragment, problems = parse(kind, answer)
    if not _usable(kind, fragment, problems):
        return {'error': '; '.join(problems) or f'{kind} returned no usable fragment.'}
    if problems:
        fragment['problems'] = problems
    return fragment
