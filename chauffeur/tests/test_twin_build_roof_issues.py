"""The roof check is told what is wrong (brief
.superpowers/sdd/2026-11-08-house-editor-whole-building-draft/task-13-brief.md,
with ruling R36).

twin_build._read_roof_check puts `issues` (services.twin_roof_issues.roof_issues
on the draft fragment after normalize, before the read) in the roof_check
context. After the corrections apply it recomputes roof_issues; every issue
left is logged in one plain line ("The roof over <area> still needs checking:
...") on the draft step, and the build never pauses for it. With no issues
and nothing else wrong, the behaviour is unchanged.

The drafts come from the recorded second-build main-house draft
(draft-main-house-2.json, build 2's raw draft before its roof check):
- RAW: as recorded. Under R36 it gives no issues: its right block, left
  bedroom and bonus room are knee-wall rooms, and it has no hip. (The visible
  roof is the envelope with overhangs, as twin_roof.js heightAt draws it; see
  test_twin_roof_issues.py.)
- HIP: r_right is a hip with ridge x, as build 2's roof check made it
  (accept/out2 plan_final.json). Over [35, 13.33, 59, 52] (24 x 38.67) it comes
  to a point, which is exactly one issue: hip_point r_right.
- FINAL: every roof section as in build 2's final plan (FINAL_ROOF_2). r_left
  and r_right both come to a point, so there are two issues.

Roof check answers:
- RESOLVE fits r_right to the second floor's right block
  [37.33, 19.33, 59, 43] at plate 20, keeping the plan's ridge x (parallel to
  the street). The block is 21.67 x 23.67, within R36's tolerance, so nothing
  is left and no line is logged.
- NO_CORRECTIONS leaves every issue, and there is one line for each.

The reader stub and harness are copied from test_twin_build_roof_check.py.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_build_roof_issues.py
"""
import copy
import io
import json
import os
import re
import sys
import tempfile
import traceback

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
from test_twin_roof_issues import FINAL_ROOF_2, hip_text  # noqa: E402

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
        if kind == 'roof_check':
            return copy.deepcopy(self.roof_answer)
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
    b = tb.start({'part': 'house'}, reader=reader, inline=True)
    st = tb.status(b)
    check(reader.kinds.count('roof_check') == 1, ('test setup: the roof check was read', reader.kinds))
    check(st['state'] == 'done', ('roof issues never pause or stop the build',
                                  st['state'], st.get('pause'), _trouble(st)))
    check(not _trouble(st), ('no error and no question', _trouble(st)))
    check(not [e for e in st['events'] if e['type'] == 'pause'],
          ('nothing pauses the build', [e for e in st['events'] if e['type'] == 'pause']))
    return b, st


def _context(reader):
    return next(c for c in reader.seen if c['kind'] == 'roof_check')['context']


def _issues(reader):
    context = _context(reader)
    check('issues' in context, ('the roof check context carries issues', sorted(context)))
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
    check(_issues(reader), 'test setup: the draft had an issue for the roof check to resolve')
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


TESTS = (
    test_context_carries_issues,
    test_no_issues_leaves_the_roof_check_unchanged,
    test_resolving_answer_logs_nothing,
    test_one_unresolved_issue_logs_one_line_without_pausing,
    test_every_leftover_issue_logs_once,
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
