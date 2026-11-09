"""Final roof consistency warnings after block derivation (R9 retarget).

Stub derivation supplies deliberately inconsistent roofs, so warning logging
is tested independently of the derivation's form decisions. The cached final
issues replace the retired roof_check context; warning protections remain.
"""
import copy
import io
import json
import os
import re
import sys
import tempfile
import traceback
from unittest.mock import patch

# Always a scratch data dir (the engine harness wipes its data dir); keep one
# an importing test module already made.
if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_build_roof_issues_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services import twin_build as tb  # noqa: E402
from services import twin_store as ts  # noqa: E402
import test_twin_build as engine_tests  # noqa: E402
from test_twin_build import Reader, _pdf, check  # noqa: E402
from test_twin_roof_issues import FINAL_ROOF_2, _box, hip_text  # noqa: E402

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
DRAFT_2 = 'draft-main-house-2.json'
STILL = re.compile(r'^The roof over .+ still needs checking: .+$')
KINDS = {'upper_walls_cut', 'hip_point', 'bears_below_floor'}
NO_CORRECTIONS = {'changes': [], 'add': [], 'remove': [], 'notes': []}
RIGHT_BLOCK = [37.33, 19.33, 59, 43]   # the second floor's right block
RESOLVE = {'changes': [{'id': 'r_right', 'rect': list(RIGHT_BLOCK), 'plate': 20}],
           'add': [], 'remove': [],
           'notes': ['The right block is a hip over the upper floor, its ridge parallel to the street.']}


# --- fixtures, reader and helpers (from test_twin_build_roof_check.py) ---------

def recorded(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)


def raw_draft():
    return recorded(DRAFT_2)


def hip_draft():
    draft = recorded(DRAFT_2)
    right = next(s for s in draft['building']['roof']['sections'] if s['id'] == 'r_right')
    right.update(kind='hip', ridge='x')
    return draft


def final_draft():
    draft = recorded(DRAFT_2)
    draft['building']['roof']['sections'] = copy.deepcopy(FINAL_ROOF_2)
    return draft


class RoofReader(Reader):
    """Answers the given main-house draft by kind, and the roof check with the
    given answer."""

    def __init__(self, draft, roof_answer=None):
        super().__init__()
        self.draft = draft
        self.roof_answer = copy.deepcopy(NO_CORRECTIONS if roof_answer is None else roof_answer)
        self.kinds = []
        self.seen = []

    def __call__(self, kind, images, context, *, run, step):
        self.kinds.append(kind)
        self.seen.append({'kind': kind, 'step': step, 'images': len(images), 'context': copy.deepcopy(context)})
        if kind in ('draft', 'draft_level'):
            return copy.deepcopy(self.draft)
        if kind == 'draft_rooms':
            return {'rooms': [], 'walls': []}
        if kind == 'outline':
            return {'error': 'The model did not answer in 120 s.'}
        if kind == 'finishes':
            return {'materials': {}}
        if kind == 'photo_map':
            return {'from_side': 'front', 'blocks': [{'id': b['id'], 'sides': ['front']} for b in context['blocks']]}
        if kind == 'roof_observe':
            return {'blocks': {b['id']: {'sides': {'front': {'kind': 'hidden'}}} for b in context['blocks']}}

        return super().__call__(kind, images, context, run=run, step=step)


def _jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), (90, 120, 160)).save(buf, format='JPEG')
    return buf.getvalue()


def _main_house():
    """The Main house as the household set it up: two floor pages, a roof
    page and one tagged photo."""
    engine_tests._fresh()
    source = ts.save_source('drawing', 'house.pdf', _pdf(3))   # legacy upload: Main house, id house
    ts.set_page_roles([
        {'source': source, 'page': 1, 'role': 'floor', 'level': 'Main floor', 'box': None, 'building': 'house'},
        {'source': source, 'page': 2, 'role': 'floor', 'level': 'Second floor', 'box': None, 'building': 'house'},
        {'source': source, 'page': 3, 'role': 'roof', 'level': None, 'box': None, 'building': 'house'}])
    ts.save_source('photo', 'house.jpg', _jpeg(), part='house')
    return source


def _house():
    return next(b for b in ts.current()['buildings'] if b['id'] == 'house')


def _trouble(st):
    return [e for e in st['events'] if e['type'] in ('error', 'question')][-3:]


def _read_rect(section):
    return (section.get('read_geometry') or {}).get('rect') or section['rect']


def _at(house, rect, tol=0.05):
    return [s for s in house['roof']['sections']
            if all(abs(a - b) <= tol for a, b in zip(_read_rect(s), rect))]


def _roof(house):
    return sorted((s['kind'], s.get('ridge'), [round(v, 2) for v in _read_rect(s)], s.get('plate'),
                   s.get('state')) for s in house['roof']['sections'])


def _run(reader):
    """One inline build of the Main house; it must finish without a pause."""
    _main_house()
    def derived(blocks, observations, evidence, choices):
        sections = copy.deepcopy(reader.draft['building'].get('roof', {}).get('sections', []))
        changes = {c['id']: c for c in reader.roof_answer.get('changes', [])}
        return [{**section, **changes.get(section['id'], {})} for section in sections], []
    with patch.object(tb.twin_roof_derive, 'derive_roof', side_effect=derived):
        b = tb.start({'part': 'house'}, reader=reader, inline=True)
    reader.build = b

    st = tb.status(b)
    check(reader.kinds.count('roof_observe') == 1, ('test setup: the roof check was read', reader.kinds))
    check(st['state'] == 'done', ('roof issues never pause or stop the build',
                                  st['state'], st.get('pause'), _trouble(st)))
    check(not _trouble(st), ('no error and no question', _trouble(st)))
    check(not [e for e in st['events'] if e['type'] == 'pause'],
          ('nothing pauses the build', [e for e in st['events'] if e['type'] == 'pause']))
    return b, st


def _context(reader):
    build = tb._BUILDS[reader.build]
    step = next(s for s in build['steps'] if s['kind'] == 'draft')
    result = json.loads(tb._cache_path(build, step).read_text(encoding='utf-8'))
    return {'issues': result['roof_blocks']['issues'],
            'sections': result['fragment']['building']['roof']['sections']}



def _issues(reader):
    context = _context(reader)
    check('issues' in context, ('the final cached result carries issues', sorted(context)))
    issues = context['issues']
    check(isinstance(issues, list), ('issues is a list', type(issues)))
    for issue in issues:
        check(isinstance(issue, dict) and isinstance(issue.get('id'), str) and issue['id']
              and issue.get('kind') in KINDS and isinstance(issue.get('text'), str) and issue['text'].strip(),
              ('each issue is {id, section?, kind, text}', issue))
    return issues


def _still(st):
    return [e for e in st['events'] if e['type'] == 'log' and 'still needs checking' in (e.get('text') or '')]


def _logs(st):
    return [e.get('text') for e in st['events'] if e['type'] == 'log']


def _summary(issues):
    return [(i['kind'], i.get('section'), i['text']) for i in issues]


# --- tests ---------------------------------------------------------------------

def test_context_carries_issues():
    reader = RoofReader(hip_draft())
    _run(reader)
    issues = _issues(reader)
    check([(i['kind'], i.get('section')) for i in issues] == [('hip_point', 'r_right')],
          ('the right hip with ridge x over 24 x 38.67 comes to a point, and nothing else is wrong',
           _summary(issues)))
    check(issues[0]['text'] == hip_text('r_right'), ('the issue text', issues[0]['text']))
    check(issues[0]['section'] in {s['id'] for s in _context(reader)['sections']},
          ('the issue names the section by its draft id', issues[0]))


def test_no_issues_leaves_the_roof_check_unchanged():
    reader = RoofReader(raw_draft())
    _, st = _run(reader)
    issues = _issues(reader)
    check(issues == [], ('the raw second draft (knee-wall rooms, no hip) gives no issues', _summary(issues)))
    check(not _still(st), ('no issues: no "still needs checking" line', _logs(st)))


def test_resolving_answer_logs_nothing():
    reader = RoofReader(hip_draft(), RESOLVE)
    _, st = _run(reader)
    check(not _issues(reader), 'the final consistency check sees the corrected roof')
    check(not _still(st), ('the issue is resolved: no "still needs checking" line', _logs(st)))
    house = _house()
    found = _at(house, RIGHT_BLOCK)
    check(len(found) == 1 and found[0]['kind'] == 'hip' and found[0].get('ridge') == 'x'
          and abs(found[0]['plate'] - 20) <= 0.01 and found[0].get('state') != 'ghost',
          ('test setup: the corrected right hip settled', _roof(house), _logs(st)))


def test_one_unresolved_issue_logs_one_line_without_pausing():
    reader = RoofReader(hip_draft(), NO_CORRECTIONS)
    _, st = _run(reader)
    check(len(_issues(reader)) == 1, ('test setup: one issue', _summary(_issues(reader))))
    lines = _still(st)
    check(len(lines) == 1, ('one issue left: exactly one plain line', _logs(st)))
    check(STILL.match(lines[0]['text']), ('the line reads "The roof over <area> still needs checking: ..."',
                                          lines[0]['text']))
    check(lines[0].get('step') == 'draft', ('the line belongs to the draft step', lines[0]))


def test_every_leftover_issue_logs_once():
    reader = RoofReader(final_draft(), NO_CORRECTIONS)
    _, st = _run(reader)
    issues = _issues(reader)
    check(len(issues) >= 2, ('test setup: build 2\'s final roof has both hips coming to a point',
                             _summary(issues)))
    lines = _still(st)
    check(len(lines) == len(issues),
          ('nothing corrected: one line for each issue the roof check was given',
           len(lines), _summary(issues), _logs(st)))
    check(all(STILL.match(e['text']) and e.get('step') == 'draft' for e in lines),
          ('each line is plain and on the draft step', [e['text'] for e in lines]))


def test_missing_fragment_section_never_logs_its_id():
    issue = {'id': 'hip_point:roof-99', 'section': 'roof-99', 'kind': 'hip_point',
             'text': hip_text('roof-99')}
    with patch.object(tb.twin_roof_issues, 'roof_issues', return_value=[issue]):
        _, st = _run(RoofReader(raw_draft()))
    lines = _still(st)
    check(len(lines) == 1, ('the leftover issue is logged', _logs(st)))
    check('Section ' not in lines[0]['text'] and 'roof-99' not in lines[0]['text'],
          ('a re-minted section id never reaches the log', lines))
    check('This section' in lines[0]['text'], ('the section has plain wording', lines))


def test_identical_leftover_texts_log_once_without_redundant_place_prefix():
    texts = [f"The upper floor's wall along the {side} stands above the roof there; "
             "the roof over it should rest at the upper floor's height."
             for side in ('left', 'right', 'rear')]
    issues = [{'id': f'upper_walls_cut:L2:w{i}', 'kind': 'upper_walls_cut',
               'text': texts[index], 'from': [i, 0], 'to': [i, 10]}
              for i, index in enumerate((0, 0, 1, 1, 2))]
    with patch.object(tb.twin_roof_issues, 'roof_issues', return_value=issues):
        reader = RoofReader(raw_draft())
        _, st = _run(reader)
    check(len(_issues(reader)) == 5, 'all five located issues stay in the final result')
    lines = [e for e in st['events'] if e['type'] == 'log' and 'stands above the roof' in e.get('text', '')]
    check([e['text'] for e in lines] == texts,
          ('five issues with three identical texts log three plain lines, without coordinates or prefix', lines))
    check(all(e.get('step') == 'draft' for e in lines), ('warnings belong to the draft step', lines))


def test_issue_detection_failure_never_stops_build():
    with patch.object(tb.twin_roof_issues, 'roof_issues', side_effect=RuntimeError('geometry warning detection failed')) as detect:
        reader = RoofReader(hip_draft(), RESOLVE)
        _, st = _run(reader)
    check(detect.call_count == 1, ('issues checked once, after derivation', detect.call_count))
    check(_issues(reader) == [], ('a failed final check supplies an empty list', _issues(reader)))
    check(_at(_house(), RIGHT_BLOCK), ('the derived roof still settles', _roof(_house())))
    check(not _still(st), ('a failed warning check leaves no warning', _logs(st)))


def test_wall_issue_context_has_feet_endpoints_without_log_coordinates():
    draft = {'building': _box(10)}
    reader = RoofReader(draft)
    _, st = _run(reader)
    issues = [i for i in _issues(reader) if i['kind'] == 'upper_walls_cut']
    check(issues, 'the low roof cuts full-height upper walls')
    walls = {w['id']: w for w in draft['building']['walls']}
    for issue in issues:
        wall = walls[issue['id'].split(':')[-1]]
        check(issue.get('from') == wall['from'] and issue.get('to') == wall['to'],
              ('the reader can locate the wall in building feet', issue, wall))
    messages = {i['text'] for i in _issues(reader)}
    lines = [e['text'] for e in st['events'] if e['type'] == 'log'
             and ('stands above the roof' in e.get('text', '') or 'beneath its full-height' in e.get('text', ''))]
    check(set(lines) == messages and len(lines) == len(messages),
          ('place-naming issues log their plain text once, without coordinates', lines, messages))


TESTS = (
    test_context_carries_issues,
    test_no_issues_leaves_the_roof_check_unchanged,
    test_resolving_answer_logs_nothing,
    test_one_unresolved_issue_logs_one_line_without_pausing,
    test_every_leftover_issue_logs_once,
    test_missing_fragment_section_never_logs_its_id,
    test_identical_leftover_texts_log_once_without_redundant_place_prefix,
    test_issue_detection_failure_never_stops_build,
    test_wall_issue_context_has_feet_endpoints_without_log_coordinates,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:400])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
