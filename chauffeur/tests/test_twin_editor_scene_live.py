"""The twin scene for the house editor, in real Chromium (spec
docs/superpowers/specs/2026-11-07-house-editor-design.md sections 6, 8; plan
docs/superpowers/plans/2026-11-07-house-editor-slice-1.md Task 4 and its
review amendment): roof sections on the envelope, translucent ghosts that are
never merged, picking settled pieces through a proxy layer, building rotation,
level keys namespaced per building, and a sheet underlay on its level.

The seeded plan is tests/fixtures/twin_lot58_main.plan.json (a simplified main
house with the Lot 58 roof sections and one ghost wall, plus the P0 pool house
as a second, rotated building) after composition. Library downloads are
stubbed as in tests/test_twin_view_live.py. Test hooks exist only with ?test=1.

Run from chauffeur/:  python tests/test_twin_editor_scene_live.py
"""
import base64
import io
import json
import os
import sys
import tempfile
import time

os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_twin_editor_scene_'))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from live_app import live_app  # noqa: E402
import test_twin_view_live as p0view  # noqa: E402  (library stubs)

GPU_ARGS = ['--use-angle=gl', '--enable-gpu', '--ignore-gpu-blocklist']
_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'twin_lot58_main.plan.json')


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _seed():
    from services import twin_compose, twin_library, twin_plan, twin_store
    twin_library._urlopen = p0view._stub_urlopen
    with open(_FIXTURE, encoding='utf-8') as f:
        plan = twin_plan.normalize(json.load(f))[0]
    plan, _ = twin_compose.compose(plan, twin_library.kit('modern_farmhouse'), seed=1)
    twin_store.push_round(plan, 'build')
    return plan


SERVED = None


def _serve():
    global SERVED
    if SERVED is None:
        SERVED = live_app(_seed)
    return SERVED


def _open(page, served):
    page.goto(served.url('house/twin?tier=high&test=1'))
    page.wait_for_function('window.__twin && window.__twin.ready === true', timeout=60000)
    time.sleep(1.0)


def _png_data_url():
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (64, 48), (240, 240, 240)).save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def scenario_roof_sections_draw_on_the_envelope():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        r = page.evaluate("() => window.__twin.roofStats('house')")
        check(r['triangles'] > 0 and r['maxError'] < 0.02, r)


def scenario_ghosts_are_translucent_and_unmerged():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        g = page.evaluate("() => window.__twin.pieceInfo('wall-ghost-1')")
        check(g['material'] == 'ghost' and abs(g['opacity'] - 0.35) < 1e-6 and g['merged'] is False
              and g['depthWrite'] is False, g)
        settled = page.evaluate("() => window.__twin.pieceInfo('wall-1')")
        check(settled['merged'] is True and settled['material'] != 'ghost', settled)


def scenario_pick_finds_settled_walls_that_share_a_merged_material():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.evaluate("() => window.__twin.setCamera('top')")
        page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        for pid in ('wall-1', 'wall-2', 'wall-ghost-1'):
            x, y = page.evaluate(f"() => window.__twin.screenOf('{pid}')")
            hit = page.evaluate(f"() => window.__twin.pick({x}, {y})")
            check(hit and hit['pieceId'] == pid and hit['buildingId'] == 'house', (pid, hit))
        check(page.evaluate("() => window.__twin.pick(-5, -5)") is None, 'off the canvas picks nothing')


def scenario_rotation_turns_the_building():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        a = page.evaluate("() => window.__twin.worldBox('wall-2')")
        page.evaluate("""async () => {
            const plan = structuredClone(window.__twin.plan);
            plan.buildings.find(b => b.id === 'house').rotation = 90;
            await window.__twin.rebuild(plan);
        }""")
        b = page.evaluate("() => window.__twin.worldBox('wall-2')")
        span = lambda box, i: box['max'][i] - box['min'][i]
        check(abs(span(a, 1) - span(b, 0)) < 0.1 and abs(span(a, 0) - span(b, 1)) < 0.1, (a, b))


def scenario_level_keys_are_namespaced_per_building():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        keys = page.evaluate("() => window.__twin.levelKeys()")
        for k in ('house:L1', 'house:L2', 'pool_house:L1', 'pool_house:L2'):
            check(k in keys, keys)
        page.evaluate("() => window.__twin.showLevels(['house:L1'])")
        vis = page.evaluate("() => window.__twin.levelVisibility()")
        check(vis['house:L1'] and not vis['house:L2'] and not vis['pool_house:L1'], vis)
        page.evaluate("() => window.__twin.showLevels(null)")
        vis = page.evaluate("() => window.__twin.levelVisibility()")
        check(all(vis.values()), vis)


def scenario_sheet_underlay_sits_on_its_level():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        url = _png_data_url()
        reg = {'scale': 0.5, 'angle': 0, 'origin_px': [0, 48], 'offset': [0, 0]}
        for level, elevation in (('L1', 0), ('L2', 10)):
            page.evaluate("(a) => window.__twin.setSheet(a)",
                          {'url': url, 'reg': reg, 'buildingId': 'house', 'levelId': level, 'opacity': 0.6})
            page.wait_for_function("() => window.__twin.sheetInfo() && window.__twin.sheetInfo().ready", timeout=10000)
            info = page.evaluate("() => window.__twin.sheetInfo()")
            check(info['visible'] and abs(info['elevationFt'] - elevation) < 0.2, (level, info))
            check(abs(info['widthFt'] - 32) < 0.01 and abs(info['depthFt'] - 24) < 0.01, info)   # 64 x 48 px at 0.5 ft
        page.evaluate("() => window.__twin.setSheet(null)")
        check(page.evaluate("() => window.__twin.sheetInfo()") is None, 'cleared')


def scenario_no_transmission_and_hooks_need_the_test_flag():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        check(page.evaluate("() => window.__twin.materialsWith('transmission')") == [], 'transmission')
        page.goto(s.url('house/twin?tier=high'))
        page.wait_for_function('window.__twin && window.__twin.ready === true', timeout=60000)
        check(page.evaluate("() => typeof window.__twin.roofStats") == 'undefined', 'hooks only with ?test=1')
        check(page.evaluate("() => typeof window.__twin.pick") == 'function', 'pick is real API, not a hook')
    check(not p0view._unexpected(s.errors()), s.errors())


OWNED_GABLE = {
    'schema': 'chauffeur.twin.plan/2', 'units': 'ft', 'materials': {}, 'site': {'lot': [[-20, -20], [50, -20], [50, 40], [-20, 40]]},
    'buildings': [{'id': 'shed', 'name': 'Shed', 'position': [0, 0], 'rotation': 0, 'base': 0,
                   'levels': [{'id': 'L1', 'name': 'Ground', 'elevation': 0, 'ceiling': 9}],
                   'walls': [{'id': 'w-front', 'level': 'L1', 'from': [0, 0], 'to': [30, 0], 'height': 9, 'thickness': 0.5, 'exterior': True},
                             {'id': 'w-right', 'level': 'L1', 'from': [30, 0], 'to': [30, 20], 'height': 9, 'thickness': 0.5, 'exterior': True},
                             {'id': 'w-rear', 'level': 'L1', 'from': [30, 20], 'to': [0, 20], 'height': 9, 'thickness': 0.5, 'exterior': True},
                             {'id': 'w-left', 'level': 'L1', 'from': [0, 20], 'to': [0, 0], 'height': 9, 'thickness': 0.5, 'exterior': True}],
                   'openings': [], 'rooms': [], 'stairs': [],
                   'roof': {'sections': [{'id': 'r1', 'kind': 'gable', 'rect': [0, 0, 30, 20], 'ridge': 'x',
                                          'pitch': 12, 'plate': 9, 'overhang': 0}], 'extensions': []}}]}


def scenario_ids_are_per_building_in_the_scene():
    # Review finding: the registry was keyed by bare id, but ids are unique per building only.
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        a = page.evaluate("() => window.__twin.worldBox('opening-1', 'house')")
        b = page.evaluate("() => window.__twin.worldBox('opening-1', 'pool_house')")
        check(a and b and a != b, (a, b))
        check(page.evaluate("() => window.__twin.worldBox('opening-1')") is None, 'an ambiguous bare id resolves to nothing')
        ids = page.evaluate("() => window.__twin.pieceIds('pool_house')")
        check(not ({'light', 'fixture', 'stair'} & {i.split(':')[-1] for i in ids}), ids[:20])
        check(len([i for i in ids if i.startswith('light')]) >= 7, 'one piece per light, not one for all')


def scenario_a_ghost_costs_at_most_two_draw_calls():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        g = page.evaluate("() => window.__twin.pieceInfo('wall-ghost-1', 'house')")
        check(g['drawCalls'] <= 2 and g['polygonOffset'] is True, g)


def scenario_a_wall_that_owns_a_gable_rises_to_the_roof():
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        page.evaluate("(plan) => window.__twin.rebuild(plan)", OWNED_GABLE)
        left = page.evaluate("() => window.__twin.worldBox('w-left', 'shed')")
        front = page.evaluate("() => window.__twin.worldBox('w-front', 'shed')")
        check(left['max'][2] > 18.5, f'the gable end wall fills the gable: {left}')
        check(front['max'][2] < 9.5, f'an eave wall stops at its height: {front}')


def scenario_secondary_gables_get_no_ground_posts():
    # Review finding: P0's gable trim (corner posts from the ground to the plate)
    # was drawn for every exposed gable, so an upper front gable sprouted posts
    # through both floors.
    s = _serve()
    if s is None:
        return
    with s.browser(launch_args=GPU_ARGS) as page:
        _open(page, s)
        box = page.evaluate("() => window.__twin.worldBox('r-front-gable', 'house')")
        check(box['min'][2] > 10, box)


if __name__ == '__main__':
    for fn in (scenario_roof_sections_draw_on_the_envelope,
               scenario_ghosts_are_translucent_and_unmerged,
               scenario_pick_finds_settled_walls_that_share_a_merged_material,
               scenario_rotation_turns_the_building,
               scenario_level_keys_are_namespaced_per_building,
               scenario_sheet_underlay_sits_on_its_level,
               scenario_no_transmission_and_hooks_need_the_test_flag,
               scenario_ids_are_per_building_in_the_scene,
               scenario_a_ghost_costs_at_most_two_draw_calls,
               scenario_a_wall_that_owns_a_gable_rises_to_the_roof,
               scenario_secondary_gables_get_no_ground_posts):
        fn()
        print('  ok ', fn.__name__)
