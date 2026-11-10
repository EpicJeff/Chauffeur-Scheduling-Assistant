"""Pieces read out of a reply as it streams (plan docs/superpowers/plans/
2026-11-10-house-guided-build-piece-4.md Task 2; brief .superpowers/sdd/
2026-11-10-house-guided-build-piece-4/task-2-brief.md).

Interface under test:
  twin_stream.Pieces(paths: dict[str, str])
      paths maps a dotted JSON path of an array ('building.walls',
      'building.roof.sections', 'rooms', ...) to a stage name.
  .feed(text) -> list[(stage, path, item)]   every array item completed by
      this text, in order, each item equal to json.loads of its own text.
  .stage -> str | None                       the stage whose array is open now.
  Tolerant of whitespace, strings holding brackets, braces and escaped
  quotes, and a code fence around the reply.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_stream.py
"""
import copy
import json
import os
import random
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_stream_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from services import twin_stream  # noqa: E402
    _IMPORT_ERROR = None
except ImportError as exc:  # the module does not exist until Task 2 lands
    twin_stream = None
    _IMPORT_ERROR = exc

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')

# The draft's arrays and the stage each one belongs to (the step strip's names).
DRAFT_PATHS = {'building.levels': 'outline', 'building.walls': 'walls', 'building.openings': 'doors and windows',
               'building.fixtures': 'fixtures', 'building.roof.sections': 'roofs', 'rooms': 'rooms'}
ROOMS_PATHS = {'rooms': 'rooms', 'walls': 'walls'}


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _ts():
    if twin_stream is None:
        raise _IMPORT_ERROR
    return twin_stream


def recorded(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)


def expected(answer, paths, prefix=''):
    """(stage, path, item) for every item of every named array, in text order."""
    out = []
    for key, value in answer.items():
        path = prefix + key
        if path in paths and isinstance(value, list):
            out += [(paths[path], path, item) for item in value]
        elif isinstance(value, dict):
            out += expected(value, paths, path + '.')
    return out


def feed_all(pieces, text, sizes):
    got = []
    i = 0
    for n in sizes:
        if i >= len(text):
            break
        returned = pieces.feed(text[i:i + n])
        check(isinstance(returned, list), f'feed returns a list: {returned!r}')
        got += returned
        i += n
    if i < len(text):
        got += pieces.feed(text[i:])
    return got


def one_at_a_time(text):
    return [1] * len(text)


def random_sizes(text, seed):
    rng = random.Random(seed)
    return [rng.choice((1, 2, 3, 5, 8, 13, 40, 97, 400)) for _ in range(len(text))]


def serialisations(answer):
    compact = json.dumps(answer)
    return {'compact': compact,
            'tight': json.dumps(answer, separators=(',', ':'), ensure_ascii=False),
            'indented': json.dumps(answer, indent=2),
            'fenced': '```json\n' + json.dumps(answer, indent=2) + '\n```\n',
            'fenced compact': '```\n' + compact + '\n```'}


def _same(got, want, label):
    check(len(got) == len(want), f'{label}: {len(got)} items, want {len(want)}')
    for i, (g, w) in enumerate(zip(got, want)):
        check(tuple(g) == w, f'{label}: item {i} is {json.dumps(list(g))[:200]}, want {json.dumps(list(w))[:200]}')


# ---------------------------------------------------------------- tests

def items_arrive_when_their_closing_brace_arrives():
    ts = _ts()
    house = recorded('draft-main-house.json')
    with_fixtures = copy.deepcopy(house)
    building = with_fixtures['building']
    # A draft written in the new output order, with fixtures between openings and roof.
    ordered = {k: building[k] for k in ('levels', 'walls', 'openings')}
    ordered['fixtures'] = [{'kind': 'light', 'level': 'L1', 'at': [10.5, 8.0], 'surface': 'ceiling'},
                           {'kind': 'switch', 'level': 'L1', 'at': [3.0, 0.0], 'surface': 'wall', 'wall': 'w1'}]
    ordered.update({k: v for k, v in building.items() if k not in ordered})
    with_fixtures['building'] = ordered
    cases = [('draft-main-house', house, DRAFT_PATHS), ('draft-main-house with fixtures', with_fixtures, DRAFT_PATHS),
             ('draft-pool-house', recorded('draft-pool-house.json'), DRAFT_PATHS),
             ('draft_rooms-main-house', recorded('draft_rooms-main-house.json'), ROOMS_PATHS)]
    for name, answer, paths in cases:
        want = expected(answer, paths)
        check(want, f'{name}: the fixture has items to stream')
        for label, text in serialisations(answer).items():
            _same(feed_all(ts.Pieces(paths), text, one_at_a_time(text)), want, f'{name} {label} one character at a time')
            for seed in (1, 2, 3):
                _same(feed_all(ts.Pieces(paths), text, random_sizes(text, seed)), want,
                      f'{name} {label} random chunks (seed {seed})')
        # The whole reply in one feed gives the same.
        _same(ts.Pieces(paths).feed(json.dumps(answer)), want, f'{name} in one feed')


def strings_with_brackets_do_not_confuse_it():
    ts = _ts()
    answer = {
        'notes': ['a note with "building": {"walls": [{"id": "fake"}]} inside it', '}]}]', '\\', '[[[{{{'],
        'building': {
            'name': 'The "Annex" {west} [B]',
            'walls': [
                {'id': 'w-[1]', 'note': 'ends with a brace }', 'from': [0, 0], 'to': [10, 0]},
                {'id': 'w"2"', 'note': 'escaped quote \\" then ] and }', 'from': [10, 0], 'to': [10, 8]},
                {'id': 'w3', 'note': 'backslash at the end \\', 'from': [10, 8], 'to': [0, 8]},
                {'id': 'w4', 'note': 'unicode ½ — \U0001F3E0 and \\u007d', 'from': [0, 8], 'to': [0, 0]},
            ],
            'openings': [{'id': 'o1', 'wall': 'w-[1]', 'kind': 'door', 'at': 2.5, 'width': 3, 'sill': 0,
                          'head': 6.8, 'why': '"[{' }],
        },
        'checks': {'walls': [{'id': 'not a building wall'}], 'front_edge': 'y=0 ]}'},
    }
    want = expected(answer, DRAFT_PATHS)
    check([w[2]['id'] for w in want] == ['w-[1]', 'w"2"', 'w3', 'w4', 'o1'], 'the expectation names the real items only')
    for label, text in (('compact', json.dumps(answer)), ('raw unicode', json.dumps(answer, ensure_ascii=False)),
                        ('indented', json.dumps(answer, indent=4))):
        _same(feed_all(ts.Pieces(DRAFT_PATHS), text, one_at_a_time(text)), want, label)
        _same(feed_all(ts.Pieces(DRAFT_PATHS), text, random_sizes(text, 7)), want, label + ' random chunks')


def half_item_at_the_end_is_not_returned():
    ts = _ts()
    answer = recorded('draft-pool-house.json')
    text = json.dumps(answer)
    walls = answer['building']['walls']
    third = json.dumps(walls[2])
    start = text.index(third)
    for cut in (start + 1, start + len(third) // 2, start + len(third) - 1):
        pieces = ts.Pieces(DRAFT_PATHS)
        got = feed_all(pieces, text[:cut], one_at_a_time(text[:cut]))
        levels = len(answer['building']['levels'])
        check([g[2] for g in got] == answer['building']['levels'] + walls[:2],
              f'cut inside the third wall: only the levels and the first two walls are whole: '
              f'{[g[2].get("id") for g in got]}')
        check(len(got) == levels + 2, 'the half wall is not returned')
        rest = pieces.feed(text[cut:])
        _same(got + rest, expected(answer, DRAFT_PATHS), f'cut at {cut - start} into the third wall, then the rest')
    # A reply that stops mid-item never yields that item, however it was cut.
    pieces = ts.Pieces(DRAFT_PATHS)
    got = pieces.feed(text[:start + len(third) - 1])
    got += pieces.feed('')
    check(len(got) == len(answer['building']['levels']) + 2, 'an empty feed completes nothing')


def stage_follows_the_open_array():
    ts = _ts()
    answer = {'pages': [{'image': 1, 'level': 'L1', 'anchors': []}],
              'building': {
                  'id': 'main', 'levels': [{'id': 'L1', 'outline': [[0, 0], [10, 0], [10, 8]]}],
                  'walls': [{'id': 'w1', 'from': [0, 0], 'to': [10, 0]}, {'id': 'w2', 'from': [10, 0], 'to': [10, 8]}],
                  'openings': [{'id': 'o1', 'wall': 'w1'}],
                  'fixtures': [{'kind': 'light', 'level': 'L1', 'at': [5, 4], 'surface': 'ceiling'}],
                  'roof': {'sections': [{'id': 'r1', 'rect': [0, 0, 10, 8]}], 'extensions': []},
                  'porches': []},
              'checks': {}, 'notes': ['done']}
    text = '```json\n' + json.dumps(answer) + '\n```'

    def stage_at(marker, offset=0):
        pieces = ts.Pieces(DRAFT_PATHS)
        cut = text.index(marker) + len(marker) + offset
        for ch in text[:cut]:
            pieces.feed(ch)
        return pieces.stage

    check(ts.Pieces(DRAFT_PATHS).stage is None, 'nothing is open before the reply starts')
    check(stage_at('```json\n{') is None, 'the reply has begun but no named array is open')
    check(stage_at('"pages": [') is None, 'an array not in the paths has no stage')
    check(stage_at('"levels": [') == 'outline', 'inside building.levels')
    check(stage_at('"outline": [') == 'outline', 'a nested array inside a level keeps its stage')
    check(stage_at('"walls": [') == 'walls', 'inside building.walls')
    check(stage_at('"id": "w2"') == 'walls', 'mid-item inside building.walls')
    check(stage_at('"to": [10, 8]') == 'walls', 'a wall point keeps the walls stage')
    walls_end = text.index('"openings"')
    pieces = ts.Pieces(DRAFT_PATHS)
    pieces.feed(text[:walls_end])
    check(pieces.stage is None, f'between the walls array and the next one nothing is open: {pieces.stage!r}')
    check(stage_at('"openings": [') == 'doors and windows', 'inside building.openings')
    check(stage_at('"fixtures": [') == 'fixtures', 'inside building.fixtures')
    check(stage_at('"sections": [') == 'roofs', 'inside building.roof.sections')
    check(stage_at('"extensions": [') is None, 'roof.extensions is not a named path')
    check(stage_at('"notes": [') is None, 'notes has no stage')
    pieces = ts.Pieces(DRAFT_PATHS)
    pieces.feed(text)
    check(pieces.stage is None, 'after the whole reply nothing is open')


def nested_arrays_inside_an_item_stay_inside_it():
    ts = _ts()
    level = {'id': 'L1', 'name': 'main', 'outline': [[0, 0], [30, 0], [30, 20], [0, 20]],
             'walls': [{'id': 'nested-wall', 'from': [0, 0], 'to': [1, 1]}],
             'rooms': [{'name': 'nested room'}],
             'roof': {'sections': [{'id': 'nested-section'}]}}
    porch = {'id': 'p1', 'polygon': [[0, -6], [10, -6], [10, 0], [0, 0]],
             'columns': [{'at': [0, -6], 'size': 0.5}, {'at': [10, -6], 'size': 0.5}]}
    answer = {'building': {'levels': [level], 'walls': [{'id': 'w1', 'from': [0, 0], 'to': [30, 0],
                                                         'segments': [[0, 1], [2, 3]]}],
                           'rooms': [{'name': 'building rooms are not the top-level rooms path'}],
                           'porches': [porch],
                           'roof': {'sections': [{'id': 'r1', 'rect': [0, 0, 30, 20],
                                                  'pitches': {'x0': 6}, 'points': [[1, [2, [3]]]]}],
                                    'extensions': []}},
              'rooms': [{'name': 'Kitchen', 'level': 'L1', 'polygon': [[0, 0], [10, 0], [10, 10]]}]}
    want = [('outline', 'building.levels', level),
            ('walls', 'building.walls', answer['building']['walls'][0]),
            ('roofs', 'building.roof.sections', answer['building']['roof']['sections'][0]),
            ('rooms', 'rooms', answer['rooms'][0])]
    check(expected(answer, DRAFT_PATHS) == want, 'the expectation is the four outer items')
    for label, text in (('compact', json.dumps(answer)), ('indented', json.dumps(answer, indent=2))):
        got = feed_all(ts.Pieces(DRAFT_PATHS), text, one_at_a_time(text))
        _same(got, want, label + ': a nested walls, rooms or sections array stays inside its item')
        check(got[0][2]['walls'][0]['id'] == 'nested-wall', 'the nested array comes back inside the level, whole')


TESTS = [
    items_arrive_when_their_closing_brace_arrives,
    strings_with_brackets_do_not_confuse_it,
    half_item_at_the_end_is_not_returned,
    stage_follows_the_open_array,
    nested_arrays_inside_an_item_stay_inside_it,
]


if __name__ == '__main__':
    passed = 0
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            print(f'FAIL {fn.__name__}: {type(exc).__name__}: {" ".join(str(exc).split())[:300]}')
            if not isinstance(exc, (AssertionError, ImportError)):
                traceback.print_exc(limit=4)
        else:
            passed += 1
            print(f'ok   {fn.__name__}')
    print(f'{passed}/{len(TESTS)} passed')
    sys.exit(0 if passed == len(TESTS) else 1)
