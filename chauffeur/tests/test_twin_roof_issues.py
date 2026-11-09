"""Roof issues found from the draft geometry (brief
.superpowers/sdd/2026-11-08-house-editor-whole-building-draft/task-13-brief.md,
with ruling R36).

services.twin_roof_issues.roof_issues(building) is pure: given a draft
fragment's building (levels with outline and elevation, walls with level,
from, to, height, exterior, thickness, and roof sections with id, kind, rect,
plate, pitch, overhang, ridge), it returns plain issues {id, section?, kind,
text} for the roof check to resolve:

- upper_walls_cut (R36): an upper level's FULL-HEIGHT exterior wall
  (exterior true, height >= 6 ft) whose top is cut by the visible roof. Cut
  means that, at the wall's outside face, the roof surface is more than 2 ft
  below the wall's top for at least 3 ft of its length. Knee walls (exterior
  false) never count. Text: "The upper floor's wall along the <side> stands
  above the roof there; the roof over it should rest at the upper floor's
  height."
- hip_point (R36 tolerance): a hip whose ridge runs along the rect's shorter
  side AND whose long - short >= 25% of short.
- bears_below_floor (R36): a section whose rect is >= 50% over an upper
  level's area, with its plate at or below that level's floor. Only areas
  whose walls are full-height exterior walls count, never a half level or a
  knee-wall room.

"The visible roof" is taken as the drawn roof envelope with overhangs, as
static/twin/twin_roof.js heightAt draws it. This is the only reading under
which draft 1 gives no upper_walls_cut: without overhangs, every gable-end and
eave wall of the centre block reads as cut.

What the recorded data shows under R36:
- draft-main-house.json (build 1) gives none of the three. Its rooms over the
  left wing and the garage are knee-wall rooms. Its right hip (ridge x over
  21.67 x 23.67) is within the tolerance.
- draft-main-house-2.json (build 2's raw draft, before its roof check) has no
  hip. Its right block, left bedroom and bonus room are all knee-wall rooms
  (k7 4 ft, k10 4 ft, k11 6.5 ft, and no wall at x 59), so it gives no
  upper_walls_cut and no bears_below_floor.
- Build 2's FINAL roof (after its roof check; accept/out2 plan_final.json,
  copied below as FINAL_ROOF_2 with the draft ids) made r_left and r_right
  hips with ridge x at plate 10. r_right (24 x 38.67) gives hip_point, and so
  does r_left (16 x 39.67), which this test does not assert. With build 2's own
  L2 walls, the final roof cuts no full-height wall: the only full-height walls
  beside the right block are the centre block's x 37.33 faces, which sit under
  r_main's gable-end overhang. R36 expected the right block to give
  upper_walls_cut; that would need full-height walls there. The hybrid test puts
  build 1's full-height right-block walls (u5-u8) under build 2's final roof,
  and they are cut.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_roof_issues.py
"""
import copy
import json
import os
import re
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_roof_issues_')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_reads', 'recorded', 'claude')
KINDS = {'upper_walls_cut', 'hip_point', 'bears_below_floor'}
WALL_TEXT = re.compile(r"^The upper floor's wall along the .+ stands above the roof there; "
                       r"the roof over it should rest at the upper floor's height\.$")

# The second build's final main-house roof (scratchpad accept/out2/plan_final.json,
# building main-house, settled rects rounded to 0.01 ft), with the draft ids of
# draft-main-house-2.json in the same order.
FINAL_ROOF_2 = [
    {'id': 'r_main', 'kind': 'gable', 'rect': [14.33, 13.33, 37.33, 52.0], 'pitch': 8, 'plate': 19, 'overhang': 1, 'ridge': 'x'},
    {'id': 'r_xgable', 'kind': 'gable', 'rect': [22.67, 13.33, 37.0, 26.0], 'pitch': 8, 'plate': 19, 'overhang': 1, 'ridge': 'y'},
    {'id': 'r_left', 'kind': 'hip', 'rect': [0.0, 14.33, 16.0, 54.0], 'pitch': 8, 'plate': 10, 'overhang': 1, 'ridge': 'x'},
    {'id': 'r_right', 'kind': 'hip', 'rect': [35.0, 13.33, 59.0, 52.0], 'pitch': 10, 'plate': 10, 'overhang': 1, 'ridge': 'x'},
    {'id': 'r_garage', 'kind': 'gable', 'rect': [37.0, 0.0, 59.0, 26.0], 'pitch': 12, 'plate': 10, 'overhang': 1, 'ridge': 'y'},
    {'id': 'r_rightwing', 'kind': 'gable', 'rect': [52.0, 22.0, 70.0, 42.0], 'pitch': 8, 'plate': 10, 'overhang': 1, 'ridge': 'x'},
    {'id': 'r_rearwing', 'kind': 'gable', 'rect': [43.33, 32.0, 59.0, 65.33], 'pitch': 10, 'plate': 10, 'overhang': 1, 'ridge': 'y'},
    {'id': 'r_kitchen', 'kind': 'shed', 'rect': [31.0, 50.0, 43.33, 59.0], 'pitch': 4, 'plate': 10, 'overhang': 1, 'low_side': 'y1'},
    {'id': 'r_screen', 'kind': 'gable', 'rect': [14.33, 50.0, 33.67, 66.0], 'pitch': 8, 'plate': 10, 'overhang': 1, 'ridge': 'y'},
    {'id': 'r_porch', 'kind': 'shed', 'rect': [14.33, 6.33, 37.0, 13.33], 'pitch': 3, 'plate': 10, 'overhang': 0.5, 'low_side': 'y0'},
    {'id': 'r_entry', 'kind': 'gable', 'rect': [14.33, 6.33, 22.67, 14.33], 'pitch': 8, 'plate': 10, 'overhang': 0.5, 'ridge': 'y'},
]


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def recorded_building(name):
    with open(os.path.join(RECORDED, name), encoding='utf-8') as f:
        return json.load(f)['building']


def final_building_2():
    building = recorded_building('draft-main-house-2.json')
    building['roof']['sections'] = copy.deepcopy(FINAL_ROOF_2)
    return building


def hip_text(sid):
    return (f'Section {sid} is a hip with its ridge across its shorter side, so it comes to a point; '
            "check the ridge direction and the section's extent against the roof plan.")


def issues_of(building):
    from services.twin_roof_issues import roof_issues
    before = copy.deepcopy(building)
    found = roof_issues(building)
    check(building == before, 'roof_issues never changes the building it is given')
    check(isinstance(found, list), ('roof_issues answers a list', type(found)))
    for issue in found:
        check(isinstance(issue, dict) and isinstance(issue.get('id'), str) and issue['id']
              and issue.get('kind') in KINDS and isinstance(issue.get('text'), str) and issue['text'].strip(),
              ('each issue is {id, section?, kind, text}', issue))
    ids = [i['id'] for i in found]
    check(len(ids) == len(set(ids)), ('issue ids are distinct', ids))
    return found


def _summary(issues):
    return [(i['kind'], i.get('section'), i['text']) for i in issues]


def _of(issues, kind, section=None):
    return [i for i in issues if i['kind'] == kind and (section is None or i.get('section') == section)]


# --- tests: the recorded drafts --------------------------------------------------

def test_first_draft_gives_nothing_for_its_storey_and_a_half_rooms():
    building = recorded_building('draft-main-house.json')
    knee = sorted(w['id'] for w in building['walls'] if w['level'] == 'L2' and not w['exterior'])
    check(knee == ['k1', 'k2', 'k3', 'k4'], ('test setup: build 1 reads knee walls on the second floor', knee))
    right = next(s for s in building['roof']['sections'] if s['id'] == 'r_right')
    check((right['kind'], right['ridge'], right['plate'], right['rect']) == ('hip', 'x', 20, [37.33, 19.33, 59, 43]),
          ('test setup: build 1 roofs the right block as a hip at the upper height', right))
    issues = issues_of(building)
    check(not _of(issues, 'upper_walls_cut'),
          ('no full-height upper wall of build 1 stands above its roof', _summary(issues)))
    check(not _of(issues, 'hip_point'),
          ("build 1's right hip (ridge x, 21.67 x 23.67) is within the tolerance", _summary(issues)))
    for sid in ('r_left', 'r_garage'):
        check(not _of(issues, 'bears_below_floor', sid),
              (sid, 'sits over a knee-wall room by design: not bearing below the floor', _summary(issues)))


def test_second_draft_knee_wall_rooms_bear_nothing():
    building = recorded_building('draft-main-house-2.json')
    issues = issues_of(building)
    for sid in ('r_left', 'r_right', 'r_garage'):
        check(not _of(issues, 'bears_below_floor', sid),
              (sid, 'is over a knee-wall room in the second draft: skipped', _summary(issues)))
    check(not _of(issues, 'hip_point'), ('the raw second draft reads no hip', _summary(issues)))


def test_second_build_final_roof_right_hip_point():
    issues = issues_of(final_building_2())
    points = _of(issues, 'hip_point', 'r_right')
    check(len(points) == 1, ('the final right hip (ridge x over 24 x 38.67) comes to a point', _summary(issues)))
    check(points[0]['text'] == hip_text('r_right'), ('the hip_point text', points[0]['text']))


def test_second_build_walls_are_knee_walls_so_nothing_is_cut():
    """What the data shows, against R36's expectation: build 2 read its right
    block as a knee-wall room, so its final plate-10 hip cuts no full-height
    upper wall."""
    building = final_building_2()
    right_block = [w for w in building['walls'] if w['level'] == 'L2' and w['id'] in ('k7', 'k10', 'k11')]
    check(len(right_block) == 3 and not any(w['exterior'] for w in right_block)
          and not any(w['level'] == 'L2' and w['from'][0] == 59 == w['to'][0] for w in building['walls']),
          ("test setup: build 2's right block has knee walls and no wall at x 59", right_block))
    issues = issues_of(building)
    check(not _of(issues, 'upper_walls_cut'), ('no full-height upper wall is cut', _summary(issues)))


def test_full_height_right_walls_under_final_hip_are_cut():
    """Build 2's final roof over build 1's full-height right-block walls (u5-u8):
    the plate-10 hip leaves them standing above the roof."""
    building = final_building_2()
    first = recorded_building('draft-main-house.json')
    building['walls'] = ([w for w in building['walls'] if w.get('id') not in ('k7', 'k10', 'k11')]
                         + [copy.deepcopy(w) for w in first['walls'] if w.get('id') in ('u5', 'u6', 'u7', 'u8')])
    issues = issues_of(building)
    cut = _of(issues, 'upper_walls_cut')
    check(cut, ('full-height right-block walls under a plate-10 hip are cut', _summary(issues)))
    for issue in cut:
        check(WALL_TEXT.match(issue['text']), ('the upper_walls_cut text', issue['text']))
    # The same walls under build 1's plate-20 right hip are not cut.
    right = next(s for s in first['roof']['sections'] if s['id'] == 'r_right')
    building['roof']['sections'] = [copy.deepcopy(right) if s['id'] == 'r_right' else s
                                    for s in building['roof']['sections']]
    issues = issues_of(building)
    check(not _of(issues, 'upper_walls_cut'),
          ('the right hip resting at the upper plate cuts nothing', _summary(issues)))


# --- tests: synthetic --------------------------------------------------------------

def _one_level(section):
    return {'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 10,
                        'outline': [[0, 0], [section['rect'][2], 0], [section['rect'][2], section['rect'][3]],
                                    [0, section['rect'][3]]]}],
            'walls': [],
            'roof': {'sections': [section]}}


def test_synthetic_hip_ridge_direction():
    hip = {'id': 'r_test', 'kind': 'hip', 'rect': [0, 0, 20, 40], 'pitch': 8, 'plate': 10, 'overhang': 1}
    issues = issues_of(_one_level({**hip, 'ridge': 'x'}))
    check([(i['kind'], i.get('section')) for i in issues] == [('hip_point', 'r_test')],
          ('a hip with ridge x over a 20 x 40 rect comes to a point', _summary(issues)))
    check(issues[0]['text'] == hip_text('r_test'), issues[0]['text'])
    check(issues_of(_one_level({**hip, 'ridge': 'y'})) == [], 'ridge y over 20 x 40 runs along its longer side')
    wide = {**hip, 'rect': [0, 0, 40, 20]}
    check([i['kind'] for i in issues_of(_one_level({**wide, 'ridge': 'y'}))] == ['hip_point'],
          'ridge y over a 40 x 20 rect comes to a point')
    check(issues_of(_one_level({**wide, 'ridge': 'x'})) == [], 'ridge x over 40 x 20 is fine')
    check(issues_of(_one_level({**hip, 'kind': 'gable', 'ridge': 'x'})) == [], 'a gable is never a hip_point')


def test_synthetic_hip_tolerance():
    hip = {'id': 'r_test', 'kind': 'hip', 'ridge': 'x', 'pitch': 10, 'plate': 10, 'overhang': 1}
    # Build 1's right block: long - short = 2 ft, 9% of the short side.
    check(issues_of(_one_level({**hip, 'rect': [0, 0, 21.67, 23.67]})) == [],
          'a nearly square hip is not flagged (long - short < 25% of short)')
    # Build 2's final right block: 14.67 ft, 61% of the short side.
    issues = issues_of(_one_level({**hip, 'rect': [0, 0, 24, 38.67]}))
    check([i['kind'] for i in issues] == ['hip_point'], ('a clearly elongated hip is flagged', _summary(issues)))
    check(issues_of(_one_level({**hip, 'rect': [0, 0, 20, 24]})) == [], '20% is under the tolerance')
    check([i['kind'] for i in issues_of(_one_level({**hip, 'rect': [0, 0, 20, 26]}))] == ['hip_point'],
          '30% is over it')


def _box(plate, exterior=True, height=8):
    """A 30 x 20 two-storey box: main floor walls 10 ft, second floor (floor at
    11 ft) walls of the given height and kind, one gable over the whole box."""
    outline = [[0, 0], [30, 0], [30, 20], [0, 20]]
    walls = []
    for level, h, ext in (('L1', 10, True), ('L2', height, exterior)):
        for i in range(4):
            walls.append({'id': f'{level}w{i}', 'level': level, 'from': list(outline[i]),
                          'to': list(outline[(i + 1) % 4]), 'height': h, 'thickness': 0.5, 'exterior': ext})
    return {'levels': [{'id': 'L1', 'name': 'Main floor', 'elevation': 0, 'ceiling': 10, 'outline': outline},
                       {'id': 'L2', 'name': 'Second floor', 'elevation': 11, 'ceiling': 8,
                        'outline': copy.deepcopy(outline)}],
            'walls': walls,
            'roof': {'sections': [{'id': 'r_box', 'kind': 'gable', 'ridge': 'x', 'rect': [0, 0, 30, 20],
                                   'pitch': 8, 'plate': plate, 'overhang': 1}]}}


def test_synthetic_upper_walls_cut():
    issues = issues_of(_box(10))
    cut = _of(issues, 'upper_walls_cut')
    check(cut, ('a one-storey roof under full-height second-floor walls cuts them', _summary(issues)))
    for issue in cut:
        check(WALL_TEXT.match(issue['text']), ('the upper_walls_cut text', issue['text']))
    check(issues_of(_box(19)) == [], 'a roof resting on the second-floor walls cuts nothing')
    check(not _of(issues_of(_box(10, exterior=False, height=4)), 'upper_walls_cut'), 'knee walls never count')
    check(not _of(issues_of(_box(10, height=5)), 'upper_walls_cut'), 'a wall under 6 ft is not full height')


def test_synthetic_bears_below_floor_only_over_full_height_walls():
    issues = issues_of(_box(10))
    bearing = _of(issues, 'bears_below_floor')
    check([i.get('section') for i in bearing] == ['r_box'],
          ('a one-storey plate over a full-height second floor bears below it', _summary(issues)))
    issues = issues_of(_box(10, exterior=False, height=4))
    check(not _of(issues, 'bears_below_floor'), ('over a knee-wall room it is skipped', _summary(issues)))


TESTS = (
    test_first_draft_gives_nothing_for_its_storey_and_a_half_rooms,
    test_second_draft_knee_wall_rooms_bear_nothing,
    test_second_build_final_roof_right_hip_point,
    test_second_build_walls_are_knee_walls_so_nothing_is_cut,
    test_full_height_right_walls_under_final_hip_are_cut,
    test_synthetic_hip_ridge_direction,
    test_synthetic_hip_tolerance,
    test_synthetic_upper_walls_cut,
    test_synthetic_bears_below_floor_only_over_full_height_walls,
)


if __name__ == '__main__':
    failed = []
    for fn in TESTS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:400])
            if not isinstance(exc, (AssertionError, ImportError)):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(TESTS) - len(failed)}/{len(TESTS)} passed')
    sys.exit(1 if failed else 0)
