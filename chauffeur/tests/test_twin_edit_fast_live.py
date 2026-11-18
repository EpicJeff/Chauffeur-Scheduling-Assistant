"""Kept editor releases, authoritative settling and queue recovery in Chromium.

Run from chauffeur/: python tests/test_twin_edit_fast_live.py
Optional Playwright/Chromium absence prints a skip. All data is scratch data.
"""
from contextlib import contextmanager
import math
import os
from pathlib import Path
from statistics import median
import sys
import tempfile
import time
import traceback

# Override even an inherited data setting before any app/harness import.
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_edit_fast_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import twin_edit_measure as M
import house_editor_model_harness as H
from live_app import live_app

POOL = 'pool-house'
OP_URL = '**/api/house/editor/op'
SERVED = None


@contextmanager
def _page():
    global SERVED
    try:
        from playwright.sync_api import Error
    except ImportError as error:
        raise M.MeasurementSkipped('playwright not installed; fast editor checks skipped') from error
    if SERVED is not None:
        # Each scenario starts from the fixture house, not the previous scenario's
        # edits: a pushed round alone keeps the earlier geometry it was assembled on.
        from services import twin_store
        twin_store.start_over()
    M._prepare(None)
    if SERVED is None:
        SERVED = live_app()
    if SERVED is None:
        raise M.MeasurementSkipped('playwright not installed; fast editor checks skipped')
    browser = SERVED.browser(launch_args=H.GPU_ARGS)
    try:
        with browser as page:
            page.set_default_timeout(15000)
            H.open_editor(page, SERVED, query='tier=low&test=1&timing=1')
            M._dismiss_alert(page)
            M._track_view_work(page)
            M._wait_settled(page)
            yield page
            assert not H.unexpected(browser.errors), browser.errors
    except Error as error:
        if "Executable doesn't exist" in str(error) or 'playwright install' in str(error):
            raise M.MeasurementSkipped('Chromium not installed; fast editor checks skipped') from error
        raise
    finally:
        if browser._pw is not None and browser._b is None:
            browser._pw.stop()


def _wall_op(wall, by=1):
    return {'op': 'move_wall', 'building': POOL, 'wall': wall, 'by': by}


def _building(page):
    return page.evaluate('(id) => window.__twin.plan.buildings.find(b => b.id === id)', POOL)


def _wall_at(building, point, exterior):
    # _prepare(None) loads household-2026-11-09.json through the schema bridge.
    # Resolve its current segments from the shown plan, not generated ~N ids.
    candidates = []
    for wall in building['walls']:
        if wall['level'] != 'L1' or bool(wall.get('exterior')) != exterior or wall.get('kind') == 'separator':
            continue
        a, b = wall['from'], wall['to']
        length2 = math.dist(a, b)**2
        t = sum((p-x)*(y-x) for p, x, y in zip(point, a, b)) / length2
        if 0 < t < 1 and math.dist(point, [x+t*(y-x) for x, y in zip(a, b)]) < .02:
            candidates.append(wall)
    assert len(candidates) == 1, (point, candidates, [(w['id'], w['level'], w.get('exterior'), w.get('kind'), w['from'], w['to'])
                                                      for w in building['walls']])
    return candidates[0]


def _move_walls(page):
    building = _building(page)
    return (_wall_at(building, [20, 12 + 1/6], False)['id'],
            _wall_at(building, [15.5, 0], True)['id'])


def _split_case(building):
    wall = _wall_at(building, [8.875, 22], True)
    joint = next(j for j in building['joints'] if j['level'] == wall['level']
                 and math.dist(j['at'], [17.75, 17 + 1/3]) < .02)
    # The room north of that joint shares the selected top boundary. Its
    # focus exposes the joint handle while the top wall remains selected.
    room = next(r for r in building['rooms'] if r['level'] == wall['level']
                and joint['id'] in r.get('joints', [])
                and any(math.dist(p, [0, 22]) < .02 for p in r['polygon']))
    return wall, room['id'], joint['id']


def _refused_case(building):
    # Pick an actual short boundary with a room focus that exposes its end.
    # Shorten it to .5 ft: local preview allows this, the server must refuse.
    walls = sorted((w for w in building['walls'] if w['level'] == 'L1'
                    and w.get('kind') != 'separator' and 1 < math.dist(w['from'], w['to']) < 6
                    and not any(o.get('wall') == w['id'] for o in building['openings'])),
                   key=lambda w: math.dist(w['from'], w['to']))
    for wall in walls:
        for room in building['rooms']:
            if room['level'] != wall['level'] or not set(wall['joints']).issubset(room.get('joints', [])):
                continue
            length = math.dist(wall['from'], wall['to'])
            destination = [a + (b-a)*.5/length for a, b in zip(wall['from'], wall['to'])]
            return wall['id'], room['id'], wall['joints'][1], destination
    raise AssertionError('Fixture has no short room boundary with an exposed joint')


def _line(page, wall):
    piece = next(w for w in _building(page)['walls'] if w['id'] == wall)
    return [piece['from'], piece['to']]


def _near_line(actual, expected, tolerance=.02):
    return all(math.dist(a, b) <= tolerance for a, b in zip(actual, expected))


def _assert_moved(page, wall, before, by=1):
    dx, dy = [b-a for a, b in zip(*before)]
    length = math.hypot(dx, dy)
    shift = [-dy / length * by, dx / length * by]
    expected = [[v+d for v, d in zip(p, shift)] for p in before]
    actual = _line(page, wall)
    assert _near_line(actual, expected), (wall, actual, expected)
    return actual


def _select(page, piece):
    page.evaluate('([id,bid]) => window.__editor.clickPiece(id,bid)', [piece, POOL])
    H.settle(page)


def _joint_drag(page, room, selected_wall, joint, destination, height=35):
    wall = next(w for w in _building(page)['walls'] if w['id'] == selected_wall)
    H.choose_floor(page, f"{POOL}:{wall['level']}")
    page.evaluate('() => window.__editor.clickPiece(null,null)')
    _select(page, room)
    _select(page, selected_wall)
    page.wait_for_function('window.__twin.ready && !window.__twin.__measureWork', timeout=60000)
    assert H.editor_state(page, 'selection')['id'] == selected_wall
    source = next(j['at'] for j in _building(page)['joints'] if j['id'] == joint)
    centre = [(a+b)/2 for a, b in zip(source, destination)]
    H.look_down(page, POOL, *centre, height=height)
    handle = next(h for h in H.editor_state(page, 'handles') if h['kind'] == 'joint' and h['id'] == joint)
    start = H.screen_of_world(page, *handle['at'], POOL)
    end = H.screen_of_world(page, *destination, handle['at'][2], POOL)
    M._mouse_release(page, start, end)


def _posted(page):
    operations = []

    def record(request):
        if request.method == 'POST' and request.url.split('?')[0].endswith('/api/house/editor/op'):
            operations.append(request.post_data_json['op'])

    page.on('request', record)
    return operations


def _pixels(path):
    # Pillow is already a requirements-twin.txt dependency; no new package.
    from PIL import Image
    with Image.open(path) as source:
        image = source.convert('RGB')
        return image.size, image.tobytes()


def _image_difference(before, after, diff_path):
    from PIL import Image, ImageChops, ImageStat
    with Image.open(before) as a, Image.open(after) as b:
        assert a.size == b.size, (a.size, b.size)
        delta = ImageChops.difference(a.convert('RGB'), b.convert('RGB'))
    delta.save(diff_path)
    overall = sum(ImageStat.Stat(delta).mean) / 3
    worst = 0
    for y in range(0, delta.height, 32):
        for x in range(0, delta.width, 32):
            tile = delta.crop((x, y, min(x+32, delta.width), min(y+32, delta.height)))
            worst = max(worst, sum(ImageStat.Stat(tile).mean) / 3)
    return overall, worst


def _fixed_picture(page, path):
    """Wait for deferred yard/material work to stop changing the frozen frame."""
    canvas = page.locator('#editor-scene canvas').first
    # The view's private rebuildWork is covered by the promise tracking above.
    M._wait_settled(page)
    previous = None
    for _ in range(40):
        page.evaluate("""async () => {
            const promises = [];
            window.__twin.scene.traverse(o => {
                for (const m of o.material ? [].concat(o.material) : [])
                    if (m.userData?.ready) promises.push(m.userData.ready);
            });
            await Promise.all(promises);
            await window.__twin.afterNextRender();
        }""")
        canvas.screenshot(path=str(path), animations='disabled')
        current = _pixels(path)
        if previous == current:
            return
        previous = current
        page.wait_for_timeout(250)
    raise AssertionError(f'The frozen canvas never stabilized: {path}')


def kept_move_matches_full_rebuild():
    # Independent fresh fixture and page for each kind of wall.
    for index, name in enumerate(('interior', 'exterior')):
        with _page() as page:
            wall = _move_walls(page)[index]
            before = _line(page, wall)
            posted = _posted(page)
            record, refused = M._wall_release(page, _wall_op(wall))
            assert refused is None, refused
            assert record['op'] == 'move_wall' and len(posted) == 1, posted
            by = posted[0]['by']
            distance = math.hypot(*by) if isinstance(by, list) else abs(by)
            assert math.isclose(distance, 1, abs_tol=.02), posted
            _assert_moved(page, wall, before)
            # Fix camera/time and let focus fades finish before freezing the
            # renderer's water/grass/effect clocks. The editor never bakes.
            H.look_at(page, POOL, (44, -38, 55), (15.5, 11, 0))
            page.mouse.move(0, 0)
            page.evaluate("""() => {
                const v=window.__twin;
                v.controls.enableDamping=false;
                v.setClock('2026-11-18T17:00:00Z'); v.setTime('day');
                v.bake?.stop();
            }""")
            page.wait_for_timeout(1800)
            page.evaluate("""() => {
                window.__fastRealNow = performance.now.bind(performance);
                const frozen = performance.now(); performance.now = () => frozen;
                window.__fastCamera = window.__twin.cameraState();
            }""")
            folder = Path(tempfile.mkdtemp(prefix=f'editor_fast_{name}_'))
            kept, rebuilt, diff = [folder / f'{part}.png' for part in ('kept', 'rebuilt', 'diff')]
            try:
                _fixed_picture(page, kept)
                plan = page.evaluate('JSON.stringify(window.__twin.plan)')
                page.evaluate("""async () => {
                    const v=window.__twin;
                    await v.rebuild(structuredClone(v.plan), {force:true});
                    v.bake?.stop(); v.setCameraState(window.__fastCamera);
                }""")
                _fixed_picture(page, rebuilt)
                assert page.evaluate('JSON.stringify(window.__twin.plan)') == plan
                overall, worst = _image_difference(kept, rebuilt, diff)
                assert overall < 2 and worst <= 12, f'{name}: canvas MAE {overall:.3f}, worst tile {worst:.3f}'
            except Exception:
                print(f'{name} screenshot artifacts: kept={kept} rebuilt={rebuilt} diff={diff}', flush=True)
                raise
            finally:
                page.evaluate('performance.now = window.__fastRealNow')


def split_keeps_selection():
    with _page() as page:
        before = _building(page)
        selected, room, joint = _split_case(before)
        top = selected['id']
        destination = [(a+b)/2 for a, b in zip(selected['from'], selected['to'])]
        posted = _posted(page)
        record, refused = M._release_record(page, lambda: _joint_drag(
            page, room, top, joint, destination), 'move_joint')
        assert refused is None, refused
        assert record['settle'] >= 0
        assert len(posted) == 1 and posted[0]['joint'] == joint, posted
        assert math.dist(posted[0]['to'], destination) < .02, posted
        after = _building(page)
        # Prove the server really split the target, rather than a harmless drag.
        top_parts = [w for w in after['walls'] if w['id'] == top or w['id'].startswith(top + '~')]
        assert len(top_parts) == 2, top_parts
        assert len(after['walls']) > len(before['walls'])
        assert math.dist(next(j['at'] for j in after['joints'] if j['id'] == joint), destination) < .02
        selection = H.editor_state(page, 'selection')
        # The split leaves the selected id on the half away from the focused room.
        # Room focus then falls back to the room itself (the rule before this
        # slice); either way the selection names something that exists.
        assert selection['building'] == POOL, selection
        if selection['kind'] == 'wall':
            assert selection['id'] in {w['id'] for w in top_parts}, selection
            assert 'wall' in page.inner_text('#piece-card h3').lower(), page.inner_text('#piece-card')
        else:
            assert selection['kind'] == 'room' and selection['id'] == room, selection
        assert page.locator('#piece-card').is_visible(), selection


def release_shows_within_bound():
    with _page() as page:
        interior, _ = _move_walls(page)
        # Warm once in both directions; the three reported samples are kept
        # releases and must all change the model by a full foot.
        for sign in (1, -1):
            _, refused = M._wall_release(page, _wall_op(interior, sign))
            assert refused is None, refused
        local = []
        for sign in (1, -1, 1):
            before = _line(page, interior)
            held = []
            page.route(OP_URL, lambda route: held.append(route))

            def release_while_server_is_held():
                M._wall_drag(page, _wall_op(interior, sign))
                page.wait_for_function("document.querySelector('#editor-save-state').textContent.trim() === 'Saving 1 change'")
                try:
                    assert len(held) == 1, held
                    # No op can have reached the server. The released frame
                    # must already have updated the view's own shown plan.
                    page.evaluate('async () => { await window.__twin.afterNextRender(); }')
                    _assert_moved(page, interior, before, sign)
                finally:
                    for route in held:
                        route.continue_()

            try:
                record, refused = M._release_record(page, release_while_server_is_held, 'move_wall')
            finally:
                page.unroute(OP_URL)
            assert refused is None, refused
            _assert_moved(page, interior, before, sign)
            local.append(record['first_frame'])
        assert all(math.isfinite(v) and v > 0 for v in local), local
        assert median(local) < 150, f'low-tier local_frame median {median(local):.1f} ms; samples={local}'


def network_drop_keeps_edit():
    with _page() as page:
        interior, _ = _move_walls(page)
        attempts = []

        def drop_once(route):
            attempts.append((time.monotonic(), route.request.post_data_json['op']))
            route.abort() if len(attempts) == 1 else route.continue_()

        page.route(OP_URL, drop_once)
        before = _line(page, interior)
        M._wall_drag(page, _wall_op(interior))
        page.wait_for_function("document.querySelector('#editor-save-state').textContent.trim() === '1 change not saved'")
        assert len(attempts) == 1, attempts
        kept = _assert_moved(page, interior, before)
        M._wait_settled(page)
        assert _near_line(_line(page, interior), kept), (kept, _line(page, interior))
        page.wait_for_function('window.__twinEditTiming.length === 1')
        assert len(attempts) == 2 and attempts[0][1] == attempts[1][1], attempts
        assert attempts[1][0] - attempts[0][0] >= .9, attempts
        assert not page.locator('#cc-alert-modal').is_visible()


def refused_step_snaps_back_alone():
    with _page() as page:
        short_wall, room, joint, destination = _refused_case(_building(page))
        _, exterior = _move_walls(page)
        held, responses = [], []
        posted = _posted(page)
        page.on('response', lambda r: responses.append(r) if r.request.method == 'POST'
                and r.url.split('?')[0].endswith('/api/house/editor/op') else None)

        def hold_first(route):
            # Let the real server judge it after both releases have occurred.
            if route.request.post_data_json['op']['op'] == 'move_joint':
                held.append(route)
            else:
                route.continue_()

        page.route(OP_URL, hold_first)
        page.evaluate("""() => {
            window.__fastNotices=[];
            const show=window.showGlobalAlert;
            window.showGlobalAlert = text => { window.__fastNotices.push(String(text)); return show(text); };
        }""")
        original = _line(page, short_wall)
        other = _line(page, exterior)
        # At this zoom the snap reach is .25 ft, so the .5 ft destination
        # cannot snap to the other endpoint and collapse to a zero-length wall.
        _joint_drag(page, room, short_wall, joint, destination, height=12)
        page.wait_for_function("document.querySelector('#editor-save-state').textContent.trim() === 'Saving 1 change'")
        assert len(held) == 1, held
        shortened = _line(page, short_wall)
        assert math.isclose(math.dist(*shortened), .5, abs_tol=.02), shortened
        M._wall_drag(page, _wall_op(exterior))
        page.wait_for_function("document.querySelector('#editor-save-state').textContent.trim() === 'Saving 2 changes'")
        _assert_moved(page, exterior, other)
        held[0].continue_()
        M._wait_settled(page)
        page.wait_for_selector('#cc-alert-modal.flex')
        page.wait_for_timeout(1200)
        assert len(posted) == 2 and [op['op'] for op in posted] == ['move_joint', 'move_wall'], posted
        assert len(responses) == 2, [(r.status, r.url) for r in responses]
        refused = next(r for r in responses if r.status in (400, 409, 422))
        assert 'A wall must be at least 1 ft long.' in str(refused.json()), refused.json()
        assert any(r.status == 200 for r in responses)
        notices = page.evaluate('window.__fastNotices')
        assert len(notices) == 1 and 'was not saved' in notices[0], notices
        assert 'A wall must be at least 1 ft long.' in page.inner_text('#cc-alert-message')
        assert _near_line(_line(page, short_wall), original), (_line(page, short_wall), original)
        _assert_moved(page, exterior, other)


def main():
    scenarios = [kept_move_matches_full_rebuild, split_keeps_selection, release_shows_within_bound,
                 network_drop_keeps_edit, refused_step_snaps_back_alone]
    passed = 0
    try:
        for scenario in scenarios:
            try:
                scenario()
            except M.MeasurementSkipped as error:
                print('  skip ', error)
                print(f'{passed}/{len(scenarios)} passed; remaining scenarios skipped')
                return 0
            except Exception:
                traceback.print_exc(limit=8)
                print('FAIL', scenario.__name__)
            else:
                passed += 1
                print('ok  ', scenario.__name__)
        print(f'{passed}/{len(scenarios)} passed')
        return int(passed != len(scenarios))
    finally:
        if SERVED is not None:
            SERVED.stop()


if __name__ == '__main__':
    sys.exit(main())
