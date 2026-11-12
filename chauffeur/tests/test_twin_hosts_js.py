"""Where a hosted piece sits, in the browser (brief .superpowers/sdd/2026-11-09-
house-connected-model-pieces-1-2/task-7-brief.md "Items"; spec docs/superpowers/
specs/2026-11-09-house-connected-model-design.md section 4.3; plan docs/
superpowers/plans/2026-11-09-house-connected-model-pieces-1-2.md Task 7 step 1,
the node test).

Module under test: static/twin/twin_hosts.js
- hostPoint(building, host, offset = 0) -> [x, y, z] in building-local feet,
  the JS mirror of services/twin_model_hosts.world_point (Task 4).

It runs on the FLAT building the generator draws (and the editor's drag
re-runs it on, plan Task 16): walls carry from/to (plus joints ids), rooms
carry their polygon. The cases are Task 4's fixture cases
(tests/test_twin_model_hosts.py): the 10 x 10 ft box on L1 (elevation 0,
ceiling 9), walls s (0,0)->(10,0), e (10,0)->(10,10), n (10,10)->(0,10),
w (0,10)->(0,0), thickness 0.5, room r1. Rules pinned, as Task 4 reads them:
- a floor host sits at the level's elevation, at u, v as fractions of the
  room's bounding box; a ceiling host at elevation + ceiling;
- a wall host is `at` feet from the wall's first end (from), z above the
  level, thickness/2 + offset off the centreline, left and right opposite.
The last scenario checks parity with the Python world_point on the schema 3
twin of each case (it needs Task 4's module).

Runs the module under node (copied to a temp .mjs, as tests/test_twin_snap_js.py
does). Skips when node is unavailable.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_hosts_js.py
"""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

if not os.environ.get('CHAUFFEUR_DATA_DIR', '').startswith(tempfile.gettempdir()):
    os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_twin_hosts_js_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, 'static', 'twin', 'twin_hosts.js')
TOL = 1e-6
THICK = 0.5


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=TOL):
    return abs(a - b) <= tol


def close_pt(a, b, tol=TOL):
    return isinstance(a, list) and len(a) == len(b) and all(close(x, y, tol) for x, y in zip(a, b))


DRIVER = r"""
import { readFileSync } from 'node:fs';
import * as hosts from './twin_hosts.mjs';
const job = JSON.parse(readFileSync(process.argv[2], 'utf8'));
console.log(JSON.stringify(job.map(c => hosts.hostPoint(c.building, c.host, c.offset ?? 0))));
"""


def run(cases):
    """cases: [(building, host, offset)] -> the list of hostPoint results."""
    if not os.path.exists(MODULE):
        raise AssertionError(f'static/twin/twin_hosts.js does not exist yet ({MODULE})')
    d = tempfile.mkdtemp(prefix='twin_hosts_js_')
    shutil.copy(MODULE, os.path.join(d, 'twin_hosts.mjs'))
    shutil.copy(os.path.join(ROOT, 'static', 'twin', 'twin_ground.js'), os.path.join(d, 'twin_ground.js'))
    with open(os.path.join(d, 'driver.mjs'), 'w', encoding='utf-8') as f:
        f.write(DRIVER)
    job = os.path.join(d, 'job.json')
    with open(job, 'w', encoding='utf-8') as f:
        json.dump([{'building': b, 'host': h, 'offset': o} for b, h, o in cases], f)
    out = subprocess.run([shutil.which('node'), os.path.join(d, 'driver.mjs'), job],
                         capture_output=True, text=True, timeout=60, cwd=d)
    if out.returncode != 0:
        raise AssertionError(out.stderr[-2000:])
    return json.loads(out.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- fixtures

def _box3(width=10, depth=10, elevation=0, level='L1'):
    """Task 4's schema 3 box: room r1 width x depth, walls s, e, n, w (CCW)."""
    return {
        'id': 'B1', 'name': 'House', 'position': [0, 0], 'rotation': 0, 'base': 0,
        'materials': {},
        'levels': [{'id': level, 'name': 'floor', 'elevation': elevation, 'ceiling': 9}],
        'joints': [
            {'id': 'j1', 'level': level, 'at': [0, 0]},
            {'id': 'j2', 'level': level, 'at': [width, 0]},
            {'id': 'j3', 'level': level, 'at': [width, depth]},
            {'id': 'j4', 'level': level, 'at': [0, depth]},
        ],
        'walls': [
            {'id': wid, 'level': level, 'joints': [a, b], 'kind': 'solid',
             'thickness': THICK, 'exterior': True, 'height': 9}
            for wid, a, b in (('s', 'j1', 'j2'), ('e', 'j2', 'j3'), ('n', 'j3', 'j4'), ('w', 'j4', 'j1'))
        ],
        'rooms': [
            {'id': 'r1', 'level': level, 'name': 'Kitchen', 'kind': 'room',
             'polygon': [[0, 0], [width, 0], [width, depth], [0, depth]],
             'joints': ['j1', 'j2', 'j3', 'j4']},
        ],
        'openings': [], 'anchors': [], 'items': [],
        'roofs': [], 'dormers': [], 'extensions': [], 'stairs': [],
        'proposals': [], 'flags': [],
    }


def _flat(b3):
    """The flat building flatten gives for a schema 3 box (walls get from/to)."""
    at = {j['id']: list(j['at']) for j in b3['joints']}
    b = copy.deepcopy(b3)
    b.pop('joints')
    for w in b['walls']:
        w['from'], w['to'] = at[w['joints'][0]], at[w['joints'][1]]
    for r in b['rooms']:
        r.pop('joints', None)
    b['roof'] = {'sections': [], 'extensions': []}
    for key in ('roofs', 'dormers'):
        b.pop(key)
    return b


def _box(width=10, depth=10, elevation=0, level='L1'):
    return _flat(_box3(width, depth, elevation, level))


# ---------------------------------------------------------------- scenarios

def scenario_floor_and_ceiling_points_are_fractions_of_the_room():
    b = _box()
    got = run([(b, {'floor': 'r1', 'u': 0.25, 'v': 0.5}, 0),
               (b, {'ceiling': 'r1', 'u': 0.5, 'v': 0.5}, 0)])
    check(close_pt(got[0], [2.5, 5, 0]), ('floor u .25 v .5', got[0]))
    check(close_pt(got[1], [5, 5, 9]), ('ceiling centre', got[1]))


def scenario_a_light_centred_in_a_room_stays_centred_when_the_room_grows():
    # Task 4's room grown to 14 x 10 (the east wall moved out 4 ft).
    b = _box(width=14)
    got = run([(b, {'ceiling': 'r1', 'u': 0.5, 'v': 0.5}, 0),
               (b, {'floor': 'r1', 'u': 0.25, 'v': 0.5}, 0)])
    check(close_pt(got[0], [7, 5, 9]), ('ceiling centre of the grown room', got[0]))
    check(close_pt(got[1], [3.5, 5, 0]), ('floor quarter of the grown room', got[1]))


def scenario_a_wall_point_sits_on_its_face():
    b = _box()
    left, right, off = run([
        (b, {'wall': 's', 'side': 'left', 'at': 4.0, 'z': 4.0}, 0),
        (b, {'wall': 's', 'side': 'right', 'at': 4.0, 'z': 4.0}, 0),
        (b, {'wall': 's', 'side': 'left', 'at': 4.0, 'z': 4.0}, 0.25),
    ])
    check(close(left[0], 4) and close(right[0], 4) and close(left[2], 4) and close(right[2], 4), (left, right))
    check(close(abs(left[1]), THICK / 2) and close(left[1], -right[1]), ('left and right faces', left, right))
    check(close(abs(off[1]), THICK / 2 + 0.25) and off[1] * left[1] > 0, ('offset off the face', left, off))


def scenario_a_switch_on_the_east_wall_and_after_the_wall_moves():
    # Task 4's rehost case: the switch on e at 3 ft, 4 ft up; then e moves +2 in x.
    host = {'wall': 'e', 'side': 'left', 'at': 3.0, 'z': 4.0}
    p, q = run([(_box(), host, 0), (_box(width=12), host, 0)])
    check(close(p[1], 3.0) and close(p[2], 4.0) and close(abs(p[0] - 10), THICK / 2), ('on e', p))
    check(close_pt(q, [p[0] + 2, p[1], p[2]]), ('rides e', p, q))


def scenario_at_is_measured_from_the_walls_first_end():
    # n runs (10,10) -> (0,10): 3 ft along it is x = 7.
    got = run([(_box(), {'wall': 'n', 'side': 'left', 'at': 3.0, 'z': 2.0}, 0)])[0]
    check(close(got[0], 7) and close(got[2], 2) and close(abs(got[1] - 10), THICK / 2), got)


def scenario_heights_are_above_the_hosts_level():
    # The same box as an upper storey: L2 at elevation 10.
    b = _box(elevation=10, level='L2')
    got = run([(b, {'floor': 'r1', 'u': 0.5, 'v': 0.5}, 0),
               (b, {'ceiling': 'r1', 'u': 0.5, 'v': 0.5}, 0),
               (b, {'wall': 's', 'side': 'left', 'at': 5.0, 'z': 4.0}, 0)])
    check(close_pt(got[0], [5, 5, 10]), ('floor of L2', got[0]))
    check(close_pt(got[1], [5, 5, 19]), ('ceiling of L2', got[1]))
    check(close(got[2][2], 14), ('a wall point 4 ft above L2', got[2]))


def scenario_the_js_mirror_agrees_with_world_point():
    # Every case above, on the schema 3 box through Task 4's world_point, and
    # on its flat twin through hostPoint.
    from services import twin_model_hosts as py
    cases = [
        ({}, {'floor': 'r1', 'u': 0.25, 'v': 0.5}, 0),
        ({}, {'ceiling': 'r1', 'u': 0.5, 'v': 0.5}, 0),
        ({'width': 14}, {'ceiling': 'r1', 'u': 0.5, 'v': 0.5}, 0),
        ({}, {'wall': 's', 'side': 'left', 'at': 4.0, 'z': 4.0}, 0),
        ({}, {'wall': 's', 'side': 'right', 'at': 4.0, 'z': 4.0}, 0),
        ({}, {'wall': 's', 'side': 'left', 'at': 4.0, 'z': 4.0}, 0.25),
        ({}, {'wall': 'e', 'side': 'left', 'at': 3.0, 'z': 4.0}, 0),
        ({}, {'wall': 'n', 'side': 'right', 'at': 3.0, 'z': 2.0}, 0),
        ({'elevation': 10, 'level': 'L2'}, {'wall': 'w', 'side': 'left', 'at': 2.0, 'z': 1.0}, 0),
    ]
    js = run([(_box(**kw), host, off) for kw, host, off in cases])
    for (kw, host, off), got in zip(cases, js):
        want = list(py.world_point(_box3(**kw), host, off))
        check(close_pt(got, want), ('hostPoint differs from world_point', kw, host, off, got, want))


SCENARIOS = (
    scenario_floor_and_ceiling_points_are_fractions_of_the_room,
    scenario_a_light_centred_in_a_room_stays_centred_when_the_room_grows,
    scenario_a_wall_point_sits_on_its_face,
    scenario_a_switch_on_the_east_wall_and_after_the_wall_moves,
    scenario_at_is_measured_from_the_walls_first_end,
    scenario_heights_are_above_the_hosts_level,
    scenario_the_js_mirror_agrees_with_world_point,
)


if __name__ == '__main__':
    if not shutil.which('node'):
        print('  ..  skipped (node not available)')
        sys.exit(0)
    failed = []
    for fn in SCENARIOS:
        try:
            fn()
        except Exception as exc:
            failed.append(fn.__name__)
            print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:500])
            if not isinstance(exc, AssertionError):
                traceback.print_exc()
        else:
            print('  ok  ', fn.__name__)
    print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
    sys.exit(1 if failed else 0)
