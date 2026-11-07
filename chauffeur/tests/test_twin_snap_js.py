"""Snapping for the house editor (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md section 6: walls snap to walls and to right
angles; plan docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task
14). Runs static/twin/editor/snap.js under node (copied to a temp .mjs).
Skips when node is unavailable.

Run from chauffeur/:  python tests/test_twin_snap_js.py
"""
import json
import os
import shutil
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE = os.path.join(ROOT, 'static', 'twin', 'editor', 'snap.js')
WALLS = [{'from': [0, 0], 'to': [10, 0]}, {'from': [10, 0], 'to': [10, 8]}]


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=1e-6):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


DRIVER = r"""
import * as snap from './snap.mjs';
const job = JSON.parse(process.argv[2]);
console.log(JSON.stringify(job.args.map(a => snap[job.call](...a))));
"""


def run(call, *args):
    d = tempfile.mkdtemp(prefix='twin_snap_js_')
    shutil.copy(MODULE, os.path.join(d, 'snap.mjs'))
    with open(os.path.join(d, 'driver.mjs'), 'w', encoding='utf-8') as f:
        f.write(DRIVER)
    out = subprocess.run([shutil.which('node'), os.path.join(d, 'driver.mjs'),
                          json.dumps({'call': call, 'args': [list(a) for a in args]})],
                         capture_output=True, text=True, timeout=60, cwd=d)
    if out.returncode != 0:
        raise AssertionError(out.stderr[-2000:])
    return json.loads(out.stdout.strip().splitlines()[-1])


def scenario_points_snap_to_endpoints_then_lines_then_grid():
    r = run('snapPoint', [[10.3, 0.2], WALLS], [[5.2, 0.4], WALLS], [[33.3, 33.3], WALLS], [[10.4, 4.1], WALLS])
    check(close(r[0], [10, 0]), ('endpoint', r[0]))
    check(close(r[1], [5.2, 0]), ('onto the wall line', r[1]))
    check(close(r[2], [33.5, 33.5]), ('grid', r[2]))
    check(close(r[3], [10, 4.1]), ('onto the second wall', r[3]))


def scenario_reach_and_grid_are_options():
    r = run('snapPoint', [[12.5, 0.1], WALLS, {'grid': 1, 'reach': 3}], [[12.5, 0.1], WALLS, {'grid': 1, 'reach': 1}])
    check(close(r[0], [10, 0]), r[0])
    check(close(r[1], [12.5, 0]) or close(r[1], [13, 0]), r[1])


def scenario_angles_snap_to_right_angles_within_seven_degrees():
    r = run('snapAngle', [[0, 0], [10, 0.9]], [[0, 0], [0.5, 10]], [[0, 0], [10, 3]], [[2, 2], [-8, 2.5]])
    check(close(r[0], [10, 0], 1e-3), r[0])                       # 5.1 degrees off: snaps
    check(close(r[1], [0, 10], 1e-3), r[1])
    check(close(r[2], [10, 3]), r[2])                             # 16.7 degrees: left alone
    check(close(r[3], [-8, 2], 1e-3), r[3])                       # snaps about its own start


def scenario_rotation_snaps_to_quarter_turns_within_seven_degrees():
    r = run('snapRotation', [86], [97], [181], [47], [-3])
    check(r[:3] == [90, 90, 180] and r[3] == 47 and r[4] == 0, r)


def scenario_lengths_parse_the_way_people_type_them():
    d = tempfile.mkdtemp(prefix='twin_cards_js_')
    shutil.copy(os.path.join(ROOT, 'static', 'twin', 'editor', 'cards.js'), os.path.join(d, 'cards.mjs'))
    driver = os.path.join(d, 'driver.mjs')
    with open(driver, 'w', encoding='utf-8') as f:
        f.write("""import { parseLength } from './cards.mjs';
const inputs = JSON.parse(process.argv[2]);
console.log(JSON.stringify(inputs.map(i => { try { return parseLength(i); } catch (e) { return null; } })));""")
    cases = ["5'6\"", '5.5', '66in', '5ft', '5 ft 6 in', "11'-0\"", '0x1A', '1e3', '', 'nonsense', 'Infinity']
    out = subprocess.run([shutil.which('node'), driver, json.dumps(cases)], capture_output=True, text=True,
                         timeout=60, cwd=d)
    if out.returncode != 0:
        raise AssertionError(out.stderr[-2000:])
    got = json.loads(out.stdout.strip().splitlines()[-1])
    check(close(got[:6], [5.5, 5.5, 5.5, 5, 5.5, 11]), got)
    check(got[6:] == [None] * 5, ('refused', got[6:]))


if __name__ == '__main__':
    if not shutil.which('node'):
        print('  ..  skipped (node not available)')
    else:
        for fn in (scenario_points_snap_to_endpoints_then_lines_then_grid,
                   scenario_reach_and_grid_are_options,
                   scenario_angles_snap_to_right_angles_within_seven_degrees,
                   scenario_rotation_snaps_to_quarter_turns_within_seven_degrees,
                   scenario_lengths_parse_the_way_people_type_them):
            fn()
            print('  ok ', fn.__name__)
