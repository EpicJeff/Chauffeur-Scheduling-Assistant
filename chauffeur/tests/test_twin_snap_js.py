"""Snapping for the house editor (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md section 6: walls snap to walls and to right
angles; plan docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task
14). Runs static/twin/editor/snap.js under node (copied to a temp .mjs).
Skips when node is unavailable.

The connected model (spec docs/superpowers/specs/2026-11-09-house-connected-
model-design.md section 5.4; plan docs/superpowers/plans/2026-11-09-house-
connected-model-pieces-1-2.md Task 11; brief .superpowers/sdd/2026-11-09-house-
connected-model-pieces-1-2/task-11-brief.md; Ruling R5) adds
snapTo(p, ctx) -> {point: [x, y], target}. snapPoint(p, walls, opts) stays a
wrapper that returns the point, so the slice-1 scenarios above it are unchanged.
- ctx = {joints, walls, below, anchors, from, grid, reach}; grid defaults to
  1/12 ft (1 in) and reach to 1 ft. joints are the flat building's joint rows
  ({id, level, at: [x, y]}); walls and below are flat walls ({from, to}) of the
  level and of the level below; anchors are plan points [x, y] (hostPoint's
  x and y); from is the fixed end of the segment being drawn or dragged, the
  origin of the right-angle snap (as snapAngle's from). Any key may be absent.
- Targets in the spec's order: 'joint', then 'line' (on a wall) and
  'extension' (a wall's line beyond its ends), then 'right_angle', 'anchor',
  'below' (a wall of the level below), 'grid'. A higher target within reach
  wins even when a lower one is nearer. The point is that target's point.

Run from chauffeur/:  env -u HA_BASE_URL python tests/test_twin_snap_js.py
"""
import json
import os
from pathlib import Path
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
    driver = os.path.join(d, 'driver.mjs')
    with open(driver, 'w', encoding='utf-8') as f:
        f.write("import { registerHooks } from 'node:module';\n"
                + "const root = " + json.dumps(Path(ROOT).as_uri() + '/') + ";\n"
                + "registerHooks({resolve(s,c,n){if(s==='three')return {url:root+'static/vendor/three-r187/three.module.js',shortCircuit:true};"
                + "if(s.startsWith('three/addons/'))return {url:root+'static/vendor/three-r187/addons/'+s.slice(13),shortCircuit:true};return n(s,c);},"
                + "load(u,c,n){return u.startsWith('file:')&&u.endsWith('.js')?{...n(u,{...c,format:'module'}),format:'module'}:n(u,c);}});\n"
                + "const {parseLength}=await import(root+'static/twin/editor/cards.js');\n" + """
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


# --- snapTo: the connected model's snapping (Task 11) ------------------------

def snap_to(*cases):
    """cases: [(point, ctx)] -> the list of snapTo results ({point, target})."""
    return run('snapTo', *[[p, ctx] for p, ctx in cases])


def is_snap(got, point, target, tol=1e-6):
    return isinstance(got, dict) and got.get('target') == target and close(got.get('point') or [], point, tol)


# One point, (5, 5), with a target of every kind within reach. Each lower kind
# is NEARER than the kinds above it, so only the order can make the higher one
# win. Distances from (5, 5):
#   joint       (5.9, 5)                                  0.9
#   line        wall y = 5.7 from (0, 5.7) to (10, 5.7)   0.7  (on the wall)
#   extension   wall x = 4.2 from (4.2, 8) to (4.2, 20)   0.8  (its line, 3 ft past its end)
#   right angle from (5.6, -2), 4.9 degrees off +y       0.6  -> (5.6, 5)
#   anchor      (5, 4.5)                                  0.5
#   below       wall y = 4.6 from (0, 4.6) to (10, 4.6)   0.4  (on the level below)
#   grid        (5, 5) is on the 1 in grid                0
# Every wall end and line crossing is more than 1 ft from (5, 5). The line is
# nearer than the extension, so it wins whether the two share a rank or not.
ORDER_P = [5, 5]
ORDER_JOINT = {'id': 'j9', 'level': 'L1', 'at': [5.9, 5]}
ORDER_LINE = {'id': 'w-line', 'from': [0, 5.7], 'to': [10, 5.7]}
ORDER_EXTENSION = {'id': 'w-ext', 'from': [4.2, 8], 'to': [4.2, 20]}
ORDER_FROM = [5.6, -2]
ORDER_ANCHOR = [5, 4.5]
ORDER_BELOW = {'id': 'w-below', 'from': [0, 4.6], 'to': [10, 4.6]}


def _order_ctx(drop=()):
    """The full ctx with the named kinds taken away."""
    walls = [w for w, name in ((ORDER_LINE, 'line'), (ORDER_EXTENSION, 'extension')) if name not in drop]
    ctx = {'joints': [] if 'joints' in drop else [ORDER_JOINT], 'walls': walls,
           'anchors': [] if 'anchors' in drop else [ORDER_ANCHOR], 'below': [] if 'below' in drop else [ORDER_BELOW],
           'grid': 1 / 12, 'reach': 1}
    if 'from' not in drop:
        ctx['from'] = ORDER_FROM
    return ctx


def snaps_in_the_spec_order():
    stages = [
        ((), [5.9, 5], 'joint'),
        (('joints',), [5, 5.7], 'line'),
        (('joints', 'line'), [4.2, 5], 'extension'),
        (('joints', 'line', 'extension'), [5.6, 5], 'right_angle'),
        (('joints', 'line', 'extension', 'from'), [5, 4.5], 'anchor'),
        (('joints', 'line', 'extension', 'from', 'anchors'), [5, 4.6], 'below'),
        (('joints', 'line', 'extension', 'from', 'anchors', 'below'), [5, 5], 'grid'),
    ]
    got = snap_to(*[(ORDER_P, _order_ctx(drop)) for drop, _, _ in stages])
    for (drop, point, target), result in zip(stages, got):
        check(is_snap(result, point, target), ('without ' + (', '.join(drop) or 'nothing'), 'want', target, point, 'got', result))
    # Reach bounds every kind but the grid: at 0.3 ft nothing above is close enough.
    got = snap_to((ORDER_P, dict(_order_ctx(), reach=0.3)))[0]
    check(is_snap(got, [5, 5], 'grid'), ('reach 0.3 leaves only the grid', got))
    # A joint on the line wall (a T at (5.9, 5.7)), 0.64 ft away, beats the
    # line itself 0.5 ft away.
    got = snap_to(([5.5, 5.2], {'joints': [{'id': 'j1', 'level': 'L1', 'at': [5.9, 5.7]}], 'walls': [ORDER_LINE]}))[0]
    check(is_snap(got, [5.9, 5.7], 'joint'), ('a joint beats a nearer wall line', got))


def extension_line_snap():
    wall_x = {'id': 'w1', 'from': [0, 0], 'to': [10, 0]}        # along +x, ends at (10, 0)
    wall_y = {'id': 'w2', 'from': [0, 0], 'to': [0, 10]}        # along +y, starts at (0, 0)
    got = snap_to(
        ([13, 0.4], {'walls': [wall_x]}),            # 3 ft past the end, 0.4 ft off the line
        ([-3, -0.2], {'walls': [wall_x]}),           # past the start
        ([0.3, -4], {'walls': [wall_y]}),            # below a vertical wall
        ([6, 0.4], {'walls': [wall_x]}),             # alongside the wall itself: a line, not an extension
        ([13, 0.9], {'walls': [wall_x]}),            # the default reach is 1 ft
        ([13, 1.5], {'walls': [wall_x]}),            # beyond reach: the grid
    )
    check(is_snap(got[0], [13, 0], 'extension'), ('past the end', got[0]))
    check(is_snap(got[1], [-3, 0], 'extension'), ('past the start', got[1]))
    check(is_snap(got[2], [0, -4], 'extension'), ('a vertical wall\'s extension', got[2]))
    check(is_snap(got[3], [6, 0], 'line'), ('on the wall it is a line', got[3]))
    check(is_snap(got[4], [13, 0], 'extension'), ('0.9 ft is within the default reach', got[4]))
    check(is_snap(got[5], [13, 1.5], 'grid'), ('1.5 ft is beyond reach', got[5]))


def grid_is_one_inch():
    got = snap_to(
        ([1.13, 2.71], {}),                          # no grid given: 1 in
        ([1.13, 2.71], {'grid': 1 / 12}),
        ([-0.04, -1.96], {}),
        ([7.5, 3.25], {}),                           # already on the grid
    )
    check(is_snap(got[0], [14 / 12, 33 / 12], 'grid'), ('the default grid is 1 in, not 6 in', got[0]))
    check(is_snap(got[1], [14 / 12, 33 / 12], 'grid'), got[1])
    check(is_snap(got[2], [0, -2], 'grid'), ('negative coordinates round to the nearest inch', got[2]))
    check(is_snap(got[3], [7.5, 3.25], 'grid'), got[3])
    # The slice-1 wrapper keeps its own default and its plain-point answer.
    legacy = run('snapPoint', [[33.3, 33.3], WALLS])[0]
    check(close(legacy, [33.5, 33.5]), ('snapPoint stays the wrapper returning a point', legacy))


SCENARIOS = [
    scenario_points_snap_to_endpoints_then_lines_then_grid,
    scenario_reach_and_grid_are_options,
    scenario_angles_snap_to_right_angles_within_seven_degrees,
    scenario_rotation_snaps_to_quarter_turns_within_seven_degrees,
    scenario_lengths_parse_the_way_people_type_them,
    snaps_in_the_spec_order,
    extension_line_snap,
    grid_is_one_inch,
]


if __name__ == '__main__':
    import sys
    if not shutil.which('node'):
        print('  ..  skipped (node not available)')
    else:
        failed = []
        for fn in SCENARIOS:
            try:
                fn()
            except Exception as exc:
                failed.append(fn.__name__)
                print('  FAIL', fn.__name__, type(exc).__name__, ' '.join(str(exc).split())[:400])
            else:
                print('  ok  ', fn.__name__)
        print(f'{len(SCENARIOS) - len(failed)}/{len(SCENARIOS)} passed')
        sys.exit(1 if failed else 0)
