"""Slice 3b acceptance in real Chromium: gizmos, snapping, typed values, split and mirror.

Run from chauffeur/: python tests/test_twin_precision_live.py
Reuses the slice 3a picking page (scratch data, a tree on clear lawn).
"""
import math
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_twin_picking_live as P  # sets scratch CHAUFFEUR_DATA_DIR before any service import
import twin_edit_measure as M
import house_editor_model_harness as H


def _centre(page, kind):
    box = page.locator(f'[data-gizmo="{kind}"]').first.bounding_box()
    assert box, f'No {kind} gizmo drawn'
    return [box['x'] + box['width'] / 2, box['y'] + box['height'] / 2]


def _select_tree(page, tool):
    tree = P._tree(page)
    P._look(page, tree['at'])
    P._click(page, P._pixel(page, tree['at']))
    P._selected(page, 'planting', tree['id'])
    page.click(f'#rail-{tool}')
    H.settle(page, 4)
    return tree


def _gizmo_drag(page, start, end, posted, *, shift=False, typed=None):
    """Press on a gizmo, move in steps, optionally type a value, release; wait for the save."""
    with page.expect_response(lambda r: r.request.method == 'POST'
                              and r.url.split('?')[0].endswith('/api/house/editor/op')) as pending:
        page.mouse.move(*start); page.mouse.down()
        if shift: page.keyboard.down('Shift')
        for k in range(1, 9):
            page.mouse.move(start[0] + (end[0] - start[0]) * k / 8, start[1] + (end[1] - start[1]) * k / 8)
            H.settle(page)
        if typed is not None:
            for ch in typed: page.keyboard.press(ch)
            page.keyboard.press('Enter')
        if shift: page.keyboard.up('Shift')
        page.mouse.up()
    assert pending.value.status == 200, pending.value.text()
    P._quiet(page)
    assert len(posted) == 1, posted
    return posted.pop()


def move_arrow_moves_along_x_in_half_feet_and_shift_frees_it():
    with P._page() as page:
        tree = _select_tree(page, 'move')
        posted = P._posted(page)
        start = _centre(page, 'gizmo_move_x')
        a, b = P._pixel(page, tree['at']), P._pixel(page, [tree['at'][0] + 3.2, tree['at'][1] + 2])
        op = _gizmo_drag(page, start, [start[0] + b[0] - a[0], start[1] + b[1] - a[1]], posted)
        moved = P._item(page, 'planting', tree['id'])['at']
        assert abs(moved[1] - tree['at'][1]) < 1e-6, (op, moved)
        dx = moved[0] - tree['at'][0]
        assert abs(dx - round(dx * 2) / 2) < 1e-6 and 2.5 <= dx <= 3.5, (op, moved)
        H.settle(page, 4)
        start = _centre(page, 'gizmo_move_x')
        a, b = P._pixel(page, moved), P._pixel(page, [moved[0] + 1.3, moved[1]])
        _gizmo_drag(page, start, [start[0] + b[0] - a[0], start[1] + b[1] - a[1]], posted, shift=True)
        free = P._item(page, 'planting', tree['id'])['at'][0] - moved[0]
        assert abs(free - round(free * 2) / 2) > .01, f'Shift drag still snapped: {free}'


def turn_ring_takes_a_typed_angle():
    with P._page() as page:
        tree = _select_tree(page, 'rotate')
        posted = P._posted(page)
        start = _centre(page, 'gizmo_turn')
        before = tree.get('rotation', 0)
        _gizmo_drag(page, start, [start[0] + 30, start[1] + 40], posted, typed='30')
        after = P._item(page, 'planting', tree['id']).get('rotation', 0)
        assert abs(((after - before - 30) + 180) % 360 - 180) < 1e-6, (before, after)


def scale_corner_doubles_and_undo_restores():
    with P._page() as page:
        tree = _select_tree(page, 'scale')
        posted = P._posted(page)
        corner = _centre(page, 'gizmo_scale')
        centre = P._pixel(page, tree['at'])
        end = [centre[0] + (corner[0] - centre[0]) * 2, centre[1] + (corner[1] - centre[1]) * 2]
        _gizmo_drag(page, corner, end, posted)
        scaled = P._item(page, 'planting', tree['id'])
        factor = scaled.get('scale', 1) / tree.get('scale', 1)
        assert 1.7 <= factor <= 2.3 and abs(factor * 20 - round(factor * 20)) < 1e-6, scaled
        page.click('#rail-undo')
        page.wait_for_function(f"window.__twin.plan.site.planting.find(p=>p.id==={tree['id']!r})?.scale==={tree.get('scale', 1)!r}"
                               f"||!window.__twin.plan.site.planting.find(p=>p.id==={tree['id']!r})?.scale")


def split_wall_from_its_card():
    with P._page() as page:
        model = H.model()
        b = model['buildings'][0]
        walls = sorted(((w, H.wall_line(model, b['id'], w['id'])) for w in b['walls'] if w.get('kind', 'solid') == 'solid'),
                       key=lambda row: -math.dist(*row[1]))
        wall, (a, c) = walls[0]
        mid = [(a[0] + c[0]) / 2, (a[1] + c[1]) / 2]
        level = next(l for l in b['levels'] if l['id'] == wall['level'])
        H.choose_floor(page, f"{b['id']}:{level['id']}")
        H.look_down(page, b['id'], *mid, height=60)
        H.click_world(page, *mid, level.get('elevation', 0) + 1, b['id'])
        selection = H.editor_state(page, 'selection')
        assert selection['id'] == wall['id'], selection
        posted = P._posted(page)
        page.get_by_role('button', name='Split wall', exact=True).click()
        assert 'Click the wall where it should split' in page.locator('#editor-status').inner_text()
        before = len(b['walls'])
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.split('?')[0].endswith('/api/house/editor/op')):
            H.click_world(page, *mid, level.get('elevation', 0) + 1, b['id'])
        P._quiet(page)
        assert posted and posted[0]['op'] == 'split_wall' and posted[0]['wall'] == wall['id'], posted
        assert abs(posted[0]['at'] - math.dist(a, c) / 2) < 1e-6, posted
        assert len(H.model()['buildings'][0]['walls']) == before + 1


def mirror_toggle_on_a_yard_object():
    with P._page() as page:
        tree = _select_tree(page, 'select')
        page.get_by_label('Mirror left-right', exact=True).check()
        page.wait_for_function(f"window.__twin.plan.site.planting.find(p=>p.id==={tree['id']!r})?.mirror_x===true")
        stored = next(p for p in H.model()['site']['planting'] if p['id'] == tree['id'])
        assert stored.get('mirror_x') is True and not stored.get('mirror_y'), stored


def main():
    scenarios = [move_arrow_moves_along_x_in_half_feet_and_shift_frees_it, turn_ring_takes_a_typed_angle,
                 scale_corner_doubles_and_undo_restores, split_wall_from_its_card, mirror_toggle_on_a_yard_object]
    names = sys.argv[1:]
    scenarios = [s for s in scenarios if not names or s.__name__ in names]
    passed = 0
    try:
        for scenario in scenarios:
            try:
                scenario()
            except M.MeasurementSkipped as error:
                print('  skip ', error); return 0
            except Exception:
                traceback.print_exc(limit=8)
                print('FAIL', scenario.__name__)
            else:
                passed += 1
                print('ok  ', scenario.__name__)
        print(f'{passed}/{len(scenarios)} passed')
        return int(passed != len(scenarios))
    finally:
        if P.SERVED is not None:
            P.SERVED.stop()


if __name__ == '__main__':
    sys.exit(main())
