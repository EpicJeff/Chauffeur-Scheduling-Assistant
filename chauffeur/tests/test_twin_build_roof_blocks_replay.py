"""Replay the household's recorded photo reads through a real build of the main
house (plan task 7 step 2, .superpowers/sdd/2026-11-08-house-editor-roofs-from-photos/
task-7-brief.md; spec docs/superpowers/specs/2026-11-08-house-editor-roofs-from-photos-design.md,
"Ground truth" and "Acceptance"; rulings R17, R18 and R19 in progress.md).

The recordings come from three real runs on the household main house with the
four device photos, tagged in this order: 22 (front), 26 (right front),
23 (left front) and 20 (rear).
- Run 1 (the fixtures): photo_map-main-house-1..4.json, roof_observe-main-house.json.
- Runs 2 and 3: photo_map-main-house-runN-1..4.json, roof_observe-main-house-runN.json.

The reader is test_twin_build_draft_replay.ReplayReader (draft and rooms from
draft-main-house.json and draft_rooms-main-house.json) with 'photo_map'
answering the recorded fragment of the photo it is shown (each photo is a
distinct colour, as in test_twin_build_roof_blocks.py) and 'roof_observe'
answering the run's recorded fragment. Block letters are build-assigned, so
blocks are found by rect within 1 ft.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_roof_blocks_replay.py
"""
import copy
import io
import os
import re
import sys
import tempfile
import traceback

# Always a scratch data dir (the engine harness wipes its data dir); keep one
# an importing test module already made.
if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_build_roof_blocks_replay_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_roof_issues  # noqa: E402
from services import twin_store as ts  # noqa: E402
from services import twin_build as tb  # noqa: E402
import test_twin_build_draft_replay as draft_replay  # noqa: E402
from test_twin_build_draft_replay import ReplayReader, recorded, _accept_all, _pdf, check  # noqa: E402

engine_tests = draft_replay.engine_tests

try:   # spec section 7: the ridge position the derivation itself uses
    from services.twin_roof_derive import _ridge as _derive_ridge  # noqa: E402
except ImportError:   # pragma: no cover - the same formula, if the helper moves
    _derive_ridge = None

TOL = 1.0
RUNS = (1, 2, 3)
# The six main blocks, by rect (the build assigns its own letters).
BLOCKS = {
    'middle': [14.33, 13.33, 37.33, 52],
    'left wing': [0, 14.33, 14.33, 54],
    'right upper': [37.33, 19.33, 59, 43],
    'garage wing': [37.33, 0, 59, 19.33],
    'rear right': [43.33, 43, 59, 65.33],
    'third garage': [59, 22, 70, 42],
}
# Photos in tag order: 22 front, 26 right front, 23 left front, 20 rear.
COLOURS = [(200, 60, 60), (60, 200, 60), (60, 60, 200), (200, 200, 60)]
PORCH_IDS = ('r_porch_shed', 'r_porch_gable', 'r_screen')
LETTER = re.compile(r'\b[B-HJ-Z]\b')   # 'A' and 'I' are words


# --- reader and build -----------------------------------------------------------

def _suffix(run):
    return '' if run == 1 else f'-run{run}'


def _jpeg(colour):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), colour).save(buf, format='JPEG')
    return buf.getvalue()


class RoofReplayReader(ReplayReader):
    """The draft replay reader, with one run's recorded photo reads."""

    def __init__(self, run, labels):
        super().__init__(recorded('draft-main-house.json'), recorded('draft_rooms-main-house.json'))
        self.maps = [recorded(f'photo_map-main-house{_suffix(run)}-{n}.json') for n in (1, 2, 3, 4)]
        self.observe = recorded(f'roof_observe-main-house{_suffix(run)}.json')
        self.labels = labels            # photo b64 -> tag index
        self.map_order = []             # tag index of each photo_map call, in call order
        self.contexts = {}

    def __call__(self, kind, images, context, *, run, step):
        if kind == 'photo_map':
            self.kinds.append(kind)
            index = self.labels.get(images[-1].get('b64')) if images else None
            self.map_order.append(index)
            self.contexts.setdefault(kind, copy.deepcopy(context))
            if index is None:
                return {'from_side': 'none', 'blocks': []}
            return copy.deepcopy(self.maps[index])
        if kind == 'roof_observe':
            self.kinds.append(kind)
            self.contexts[kind] = copy.deepcopy(context)
            return copy.deepcopy(self.observe)
        return super().__call__(kind, images, context, run=run, step=step)


_BUILT = {}


def build(run):
    """Build the main house with one run's recordings; cached per run.
    Returns {'house', 'status', 'reader'}."""
    if run in _BUILT:
        return _BUILT[run]
    draft = recorded('draft-main-house.json')
    engine_tests._fresh()
    source = ts.save_source('drawing', 'house.pdf', _pdf(3))   # legacy upload: Main house, id house
    names = [l['name'] for l in sorted(draft['building']['levels'], key=lambda l: l['elevation'])]
    ts.set_page_roles([
        {'source': source, 'page': 1, 'role': 'floor', 'level': names[0], 'box': None, 'building': 'house'},
        {'source': source, 'page': 2, 'role': 'floor', 'level': names[1], 'box': None, 'building': 'house'},
        {'source': source, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'}])
    labels = {}
    for index, colour in enumerate(COLOURS):
        sid = ts.save_source('photo', f'photo-{index + 1}.jpg', _jpeg(colour), part='house')
        labels[ts.source_images(sid)[0]['b64']] = index
    check(len(labels) == 4, ('test setup: four distinct photos', len(labels)))
    reader = RoofReplayReader(run, labels)
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = _accept_all(b)
    check(st['state'] == 'done', (run, 'the replay build finishes', st['state'], st.get('pause'),
                                  [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]))
    house = next(h for h in ts.current()['buildings'] if h['id'] == 'house')
    _BUILT[run] = {'house': copy.deepcopy(house), 'status': copy.deepcopy(st), 'reader': reader}
    return _BUILT[run]


# --- helpers ----------------------------------------------------------------------

def _near(rect, want, tol=TOL):
    return (isinstance(rect, (list, tuple)) and len(rect) == 4
            and all(abs(float(a) - float(b)) <= tol for a, b in zip(rect, want)))


def _read_rect(section):
    return (section.get('read_geometry') or {}).get('rect') or section['rect']


def _block_rect(section):
    return section.get('block') or _read_rect(section)


def _roof(house):
    return sorted((s['kind'], s.get('ridge'), [round(v, 2) for v in _read_rect(s)], s.get('ends'),
                   s.get('dormer_of') is not None, s.get('state')) for s in house['roof']['sections'])


def _carriers(house):
    """The one main (non-dormer) section over each of the six blocks."""
    out = {}
    for name, rect in BLOCKS.items():
        found = [s for s in house['roof']['sections'] if not s.get('dormer_of') and _near(_block_rect(s), rect)]
        check(len(found) == 1, ('one roof section carries the block', name, rect, _roof(house)))
        check(found[0].get('state') != 'ghost', ('the block roof settles', name, found[0].get('why')))
        out[name] = found[0]
    return out


def _ends(section):
    """Both ends along the ridge; a missing end is the kind's own end."""
    default = 'hip' if section['kind'] == 'hip' else 'gable'
    ridge = section.get('ridge') or 'x'
    ends = section.get('ends') or {}
    return {f'{ridge}{i}': ends.get(f'{ridge}{i}', default) for i in (0, 1)}


def _form(section):
    return (section['kind'], section.get('ridge'), tuple(sorted(_ends(section).items())))


def _ridge_at(section):
    """Ridge position in plan, the way twin_roof_derive._ridge places it:
    weighted by the per-eave pitches across the ridge."""
    if _derive_ridge is not None:
        return _derive_ridge(section)[0]
    axis = 1 if section.get('ridge') == 'x' else 0
    eaves = (f"{'y' if axis else 'x'}0", f"{'y' if axis else 'x'}1")
    lo, hi = section['rect'][axis], section['rect'][axis + 2]
    pitches = section.get('pitches', {})
    a, b = (pitches.get(end, section['pitch']) / 12 for end in eaves)
    return (a * lo + b * hi) / (a + b)


def _draft_step(st):
    return next(s for s in st['steps'] if s['kind'] == 'draft')


def _flags(st):
    flags = _draft_step(st).get('roof_flags')
    check(isinstance(flags, list), ('the draft step stores its roof flags', sorted(_draft_step(st))))
    return flags


# --- run 1: the ground truth ------------------------------------------------------

def test_recorded_ids_name_the_builds_blocks():
    reader = build(1)['reader']
    check(reader.map_order == [0, 1, 2, 3], ('photo_map reads each photo once, in tag order', reader.map_order))
    given = {b['id']: b['rect'] for b in reader.contexts.get('roof_observe', {}).get('blocks') or []}
    for name, rect in BLOCKS.items():
        check(any(_near(r, rect) for r in given.values()), ('the build offers the block', name, given))
    for run in RUNS:
        ids = set(recorded(f'roof_observe-main-house{_suffix(run)}.json')['blocks'])
        for n in (1, 2, 3, 4):
            ids |= {b['id'] for b in recorded(f'photo_map-main-house{_suffix(run)}-{n}.json')['blocks']}
        check(ids <= set(given), ('the recorded block ids are the build\'s block ids', run, sorted(ids), given))


def test_no_hips_on_the_main_blocks():
    house = build(1)['house']
    for name, s in _carriers(house).items():
        check(s['kind'] != 'hip' and 'hip' not in (s.get('ends') or {}).values(),
              ('there are no hips', name, s['kind'], s.get('ends')))


def test_main_block_forms():
    by = _carriers(build(1)['house'])
    want = {'middle': ('x', {'x0': 'gable'}), 'left wing': ('x', {}), 'right upper': ('x', {}),
            'garage wing': ('y', {}), 'third garage': ('x', {'x1': 'gable'}), 'rear right': ('y', {})}
    for name, (ridge, ends) in want.items():
        s = by[name]
        check((s['kind'], s.get('ridge')) == ('gable', ridge),
              (name, f'is a gable with ridge {ridge}', s['kind'], s.get('ridge'), s.get('ends')))
        for end, style in ends.items():
            check(_ends(s)[end] == style, (name, f'its {end} end is a {style} end', s.get('ends')))


def test_one_front_dormer_on_the_middle():
    house = build(1)['house']
    dormers = [s for s in house['roof']['sections'] if s.get('dormer_of')]
    over = [s for s in dormers if _near(s['dormer_of'], BLOCKS['middle'])]
    check(len(over) == 1, ('exactly one dormer over the middle', [(s['rect'], s['dormer_of']) for s in dormers]))
    d = over[0]
    r = _read_rect(d)
    check(d.get('ridge') == 'y', ('the dormer ridge runs across the street', d.get('ridge')))
    check(abs((r[0] + r[2]) / 2 - 30) <= TOL and abs((r[2] - r[0]) - 15) <= TOL,
          ('the dormer is centred about 30 ft and about 15 ft wide', r))
    check(d.get('state') != 'ghost', ('the dormer settles', d.get('why')))


def test_one_ridge_line():
    by = _carriers(build(1)['house'])
    at = {name: round(_ridge_at(by[name]), 3) for name in ('left wing', 'middle', 'right upper')}
    check(max(at.values()) - min(at.values()) <= .5,
          ('the left wing, middle and right upper share one ridge line in plan within 0.5 ft', at,
           {n: (by[n]['rect'], by[n].get('pitch'), by[n].get('pitches')) for n in at}))


def test_middle_ridge_check_flag():
    # Ruling R18: the photos read the middle's slope as 'same' in 3 of 3 runs, so
    # its lower pitch is a known limit and is not asserted. The spec section 7
    # ridge check must flag it instead, and the person fixes the pitch once.
    flags = _flags(build(1)['status'])
    hits = [f['text'] for f in flags if 'The middle upper roof' in f['text'] and 'six feet above' in f['text']]
    check(hits, ('the middle upper roof is flagged by the ridge check', [f['text'] for f in flags]))


def test_gable_windows_settle():
    house = build(1)['house']
    windows = [o for o in house.get('openings', []) if o.get('section')]
    check(len(windows) >= 3, ('at least three gable windows', len(windows)))
    ghosts = [(o.get('id'), o.get('section'), o.get('why')) for o in windows if o.get('state') == 'ghost']
    check(not ghosts, ('every gable window settles', ghosts))


def test_awning_settles():
    exts = build(1)['house']['roof'].get('extensions') or []
    check(len(exts) == 1 and exts[0].get('state') != 'ghost', ('the one roof extension settles', exts))


def test_porch_roofs_kept():
    house = build(1)['house']
    for section in recorded('draft-main-house.json')['building']['roof']['sections']:
        if section['id'] not in PORCH_IDS:
            continue
        found = [s for s in house['roof']['sections'] if _near(_read_rect(s), section['rect'], .05)]
        check(len(found) == 1, ('the porch roof is kept', section['id'], _roof(house)))
        check((found[0]['kind'], found[0].get('ridge'), found[0].get('low_side'))
              == (section['kind'], section.get('ridge'), section.get('low_side'))
              and found[0].get('state') != 'ghost', ('the porch roof keeps its read form', section['id'], found[0]))


def test_no_roof_issues_on_the_main_roof():
    house = build(1)['house']
    carriers = _carriers(house)
    ids = {s['id'] for s in carriers.values()}
    rects = [s['rect'] for s in carriers.values()]

    def on_carrier(issue):
        if issue.get('section') in ids:
            return True
        if 'from' in issue and 'to' in issue:
            mid = [(issue['from'][i] + issue['to'][i]) / 2 for i in (0, 1)]
            return any(r[0] - .5 <= mid[0] <= r[2] + .5 and r[1] - .5 <= mid[1] <= r[3] + .5 for r in rects)
        return False

    issues = [i for i in twin_roof_issues.roof_issues(copy.deepcopy(house)) if on_carrier(i)]
    check(not issues, ('roof_issues reports nothing on the six main carriers', issues))


# --- R19: determinism across the three runs --------------------------------------

def test_three_runs_derive_identical_forms():
    forms = {run: {name: _form(s) for name, s in _carriers(build(run)['house']).items()} for run in RUNS}
    differ = {name: {run: forms[run][name] for run in RUNS} for name in BLOCKS
              if len({forms[run][name] for run in RUNS}) > 1}
    check(not differ, ('the six main blocks derive identical forms in all three runs', differ))


# --- R17: flags only for what decides something ----------------------------------

def test_flags_are_plain_and_decisive():
    built = build(1)
    st, house = built['status'], built['house']
    flags = _flags(st)
    logs = [e.get('text') for e in st['events'] if e['type'] == 'log']
    # A hidden eave side decides nothing (R17): front/rear on a ridge-x block,
    # and the same rule's mirror, left/right on a ridge-y block.
    eaves = {axis: [_block_rect(s) for s in house['roof']['sections']
                    if not s.get('dormer_of') and s.get('ridge') == axis and s.get('block')]
             for axis in ('x', 'y')}
    problems = []
    for f in flags:
        text = f.get('text') or ''
        if not (text.strip() and text[0].isupper() and text.rstrip()[-1] in '.!?'):
            problems.append(('not a plain sentence', text))
        if 'roof-' in text or LETTER.search(text) or re.search(r'[\[\]{}_=<>|]', text):
            problems.append(('names an id or letter', text))
        if logs.count(text) != 1:
            problems.append(('logged other than once', logs.count(text), text))
        if (any(_near(f.get('block_rect'), r) for r in eaves['x'])
                and re.search(r'\b(front|rear) side\b', text)):
            problems.append(('names an eave side of a ridge-x block', text))
        if (any(_near(f.get('block_rect'), r) for r in eaves['y'])
                and re.search(r'\b(left|right) side\b', text)):
            problems.append(('names an eave side of a ridge-y block', text))
    unseen = {}
    for f in flags:
        if 'not visible' in (f.get('text') or ''):
            key = tuple(round(v, 1) for v in f.get('block_rect') or ())
            unseen.setdefault(key, []).append(f['text'])
    problems += [('more than one not-visible line for a block', key, texts)
                 for key, texts in unseen.items() if len(texts) > 1]
    check(not problems, (f'{len(problems)} flag problem(s) among {len(flags)} flags', problems))


def test_height_flags_compare_same_storey_and_use_plain_places():
    for run in RUNS:
        built = build(run)
        flags = _flags(built['status'])
        height = [f['text'] for f in flags if 'six feet above' in f['text']]
        check(any('middle' in text for text in height), (run, height))
        check(not any('right upper' in text for text in height), (run, height))
        check(not any(re.search(r'roof over the (left|right|middle)', f['text']) for f in flags), flags)


TESTS = (
    test_height_flags_compare_same_storey_and_use_plain_places,
    test_recorded_ids_name_the_builds_blocks,
    test_no_hips_on_the_main_blocks,
    test_main_block_forms,
    test_one_front_dormer_on_the_middle,
    test_one_ridge_line,
    test_middle_ridge_check_flag,
    test_gable_windows_settle,
    test_awning_settles,
    test_porch_roofs_kept,
    test_no_roof_issues_on_the_main_roof,
    test_three_runs_derive_identical_forms,
    test_flags_are_plain_and_decisive,
)


if __name__ == '__main__':
    verbose = '-v' in sys.argv
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:600])
            if verbose:
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
