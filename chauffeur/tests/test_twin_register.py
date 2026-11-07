"""Registration math for the house editor (spec docs/superpowers/specs/
2026-11-07-house-editor-design.md section 7.3; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 2): sheet
pixels into one building frame, outline fitting, building placement on the
lot, feet-inches. Pure: no storage, no browser, no network.

Run from chauffeur/:  python tests/test_twin_register.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import twin_register  # noqa: E402


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def close(a, b, tol=1e-6):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


def expect_value_error(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('expected ValueError')


def rot(p, deg, shift=(0, 0)):
    a = math.radians(deg)
    return [p[0] * math.cos(a) - p[1] * math.sin(a) + shift[0],
            p[0] * math.sin(a) + p[1] * math.cos(a) + shift[1]]


def add(p, q):
    return [p[0] + q[0], p[1] + q[1]]


def scenario_apply_flips_sheet_y():
    reg = twin_register.make(0.1, origin_px=(100, 200))
    check(close(twin_register.apply(reg, (150, 200)), [5, 0]), 'x runs right')
    check(close(twin_register.apply(reg, (100, 100)), [0, 10]), 'up the sheet is toward the rear')
    check(close(twin_register.invert(reg, [5, 10]), [150, 100]), 'inverse')
    check(set(reg) == {'scale', 'angle', 'origin_px', 'offset'}, sorted(reg))


def scenario_rotation_is_counterclockwise():
    reg = twin_register.make(1.0, angle=90)
    check(close(twin_register.apply(reg, (10, 0)), [0, 10]), twin_register.apply(reg, (10, 0)))
    reg = twin_register.make(0.5, angle=30, origin_px=(40, 60), offset=(7, -2))
    for p in [(0, 0), (1000, 20), (333, 777)]:
        check(close(twin_register.invert(reg, twin_register.apply(reg, p)), list(p), 1e-6), p)


def scenario_scale_from_the_70_foot_dimension():
    check(abs(twin_register.from_dimension((100, 50), (1500, 50), 70.0) - 0.05) < 1e-9, 'ft per px')
    expect_value_error(lambda: twin_register.from_dimension((0, 0), (0, 0.5), 10))
    expect_value_error(lambda: twin_register.from_dimension((0, 0), (100, 0), 0))
    expect_value_error(lambda: twin_register.from_dimension((0, 0), (100, 0), -3))


def scenario_two_points_recover_a_transform():
    truth = twin_register.make(0.05, angle=30, origin_px=(0, 0), offset=(12, -3))
    a, b = (200, 400), (900, 120)
    reg = twin_register.from_two_points(a, b, twin_register.apply(truth, a), twin_register.apply(truth, b))
    for p in [(0, 0), (1000, 1000), (333, 77)]:
        check(close(twin_register.apply(reg, p), twin_register.apply(truth, p), 1e-6), p)
    expect_value_error(lambda: twin_register.from_two_points((5, 5), (5, 5), [0, 0], [1, 1]))


def scenario_fit_outline_finds_quarter_turn_and_shift():
    fixed = [[0, 0], [70, 0], [70, 40], [30, 40], [30, 65.33], [0, 65.33]]
    moved = [rot(p, 90, shift=(5, -2)) for p in fixed]
    move, rms = twin_register.fit_outline(moved, fixed)
    back = [add(rot(p, move['angle']), move['offset']) for p in moved]
    check(rms < 0.05 and all(close(x, y, 0.05) for x, y in zip(back, fixed)), (move, rms))
    check(set(move) == {'angle', 'offset'}, sorted(move))


def scenario_fit_outline_refines_a_small_tilt():
    fixed = [[0, 0], [70, 0], [70, 40], [30, 40], [30, 65.33], [0, 65.33]]
    moved = [rot(p, 3.0, shift=(1.5, 0.75)) for p in fixed]
    move, rms = twin_register.fit_outline(moved, fixed)
    back = [add(rot(p, move['angle']), move['offset']) for p in moved]
    check(rms < 0.05 and all(close(x, y, 0.05) for x, y in zip(back, fixed)), (move, rms))


def scenario_world_rotation_and_feet_inches():
    b = {'position': [10, 20], 'rotation': 90}
    check(close(twin_register.to_world(b, [5, 0]), [10, 25]), 'rotated then placed')
    check(close(twin_register.to_local(b, [10, 25]), [5, 0]), 'inverse')
    check(close(twin_register.to_world({'position': [0, 0]}, [3, 4]), [3, 4]), 'rotation defaults to 0')
    check(twin_register.feet_inches(70.0) == "70'-0\"", twin_register.feet_inches(70.0))
    check(twin_register.feet_inches(65.3333) == "65'-4\"", twin_register.feet_inches(65.3333))
    check(twin_register.feet_inches(11.99) == "12'-0\"", 'rounds to the inch')
    check(twin_register.feet_inches(0.5) == "0'-6\"", twin_register.feet_inches(0.5))


L_SHAPE = [[0, 0], [70, 0], [70, 40], [30, 40], [30, 65.33], [0, 65.33]]


def _move_back(move, p):
    return add(rot(p, move['angle']), move['offset'])


def scenario_fit_outline_matches_edges_not_vertices():
    # Review finding: a read outline never shares the settled outline's vertex list.
    dense = []
    for i, p in enumerate(L_SHAPE):
        q = L_SHAPE[(i + 1) % len(L_SHAPE)]
        dense += [p, [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2]]
    moved = [rot(p, 90, shift=(5, -2)) for p in dense]
    move, rms = twin_register.fit_outline(moved, L_SHAPE)
    check(rms < 0.05, (move, rms))
    for p in L_SHAPE:
        check(close(_move_back(move, rot(p, 90, shift=(5, -2))), p, 0.05), (p, move))


def scenario_fit_outline_tolerates_a_cut_corner():
    traced = [[0, 0], [70, 0], [70, 36], [66, 40], [30, 40], [30, 65.33], [0, 65.33]]
    moved = [rot(p, 3.0, shift=(1.5, 0.75)) for p in traced]
    move, rms = twin_register.fit_outline(moved, L_SHAPE)
    for p in ([0, 0], [0, 65.33], [70, 0]):
        check(close(_move_back(move, rot(p, 3.0, shift=(1.5, 0.75))), p, 0.3), (p, move, rms))


def scenario_symmetric_outline_prefers_the_smallest_turn_and_shows_the_runner_up():
    rect = [[0, 0], [30, 0], [30, 20], [0, 20]]
    moved = [rot(p, 2.0) for p in rect]
    move, rms = twin_register.fit_outline(moved, rect)
    check(abs(move['angle'] + 2.0) < 0.1 and rms < 0.05, (move, rms))
    candidates = twin_register.fit_outline_candidates(moved, rect)
    check(candidates[0][0] == move and candidates[0][1] == rms, 'first candidate is the fit')
    check(len(candidates) >= 2 and candidates[1][1] - candidates[0][1] < 0.1, candidates[:2])
    check(abs(abs(candidates[1][0]['angle'] + 2.0) - 180) < 0.5, 'the runner-up is the half turn')
    check([c[1] for c in candidates] == sorted(c[1] for c in candidates), 'sorted by rms')


def scenario_feet_inches_refuses_non_finite():
    for bad in (float('nan'), float('inf')):
        expect_value_error(lambda: twin_register.feet_inches(bad))


if __name__ == '__main__':
    for fn in (scenario_apply_flips_sheet_y,
               scenario_rotation_is_counterclockwise,
               scenario_scale_from_the_70_foot_dimension,
               scenario_two_points_recover_a_transform,
               scenario_fit_outline_finds_quarter_turn_and_shift,
               scenario_fit_outline_refines_a_small_tilt,
               scenario_world_rotation_and_feet_inches,
               scenario_fit_outline_matches_edges_not_vertices,
               scenario_fit_outline_tolerates_a_cut_corner,
               scenario_symmetric_outline_prefers_the_smallest_turn_and_shows_the_runner_up,
               scenario_feet_inches_refuses_non_finite):
        fn()
        print('  ok ', fn.__name__)
