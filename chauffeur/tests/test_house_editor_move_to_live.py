"""Task 2 Chromium acceptance: Move to, one undo, visibility/lock and refusal UI.

Run from chauffeur/: python tests/test_house_editor_move_to_live.py
Uses the connected household harness; actual clicks and Ctrl+Z perform edits.
"""
from contextlib import contextmanager
import math
import os
from pathlib import Path
import sys
import tempfile

os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_move_to_live_')
os.environ.pop('HA_BASE_URL', None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import house_editor_model_harness as H

BID = 'pool-house'
CHAIR = 'move-to-chair'
WALL_ITEM = 'move-to-wall-item'
SHOTS = Path(tempfile.mkdtemp(prefix='move_to_live_shots_'))


def _stub_urlopen(req, timeout=None):
    # The harness stub serves an empty glTF for every model, which leaves the chair
    # with nothing to draw or pick. Serve the generator test's 1 m cube for it.
    from test_twin_generator_model_live import CUBE
    if req.full_url.endswith('.gltf') and 'mid_century_lounge_chair' in req.full_url:
        return H.p0view._Resp(CUBE)
    return H.p0view._stub_urlopen(req, timeout)


def fixture(plan):
    b = H.building(plan, BID)
    room = b['rooms'][0]
    b.setdefault('items', []).extend([
        {'id': CHAIR, 'asset': 'mid_century_lounge_chair', 'name': 'Reading chair',
         'host': {'floor': room['id'], 'u': .2, 'v': .3}, 'rotation': 17,
         'scale': 1.1, 'tint': '#7a6040', 'casts_shadow': False,
         'object_kind': 'decor', 'elevation': .2, 'state': 'settled'},
        {'id': WALL_ITEM, 'asset': 'mid_century_lounge_chair', 'name': 'Wall piece',
         'host': {'wall': b['walls'][0]['id'], 'at': 4, 'z': 3, 'side': 'left'},
         'state': 'settled'},
    ])
    return plan


@contextmanager
def editor():
    served = H.serve(fixture)
    assert served is not None, 'Playwright is required for this acceptance check'
    from services import twin_library, twin_store
    twin_library._urlopen = _stub_urlopen
    twin_store.start_over()
    twin_store.push_round(fixture(H.household_plan()), 'build')
    browser = served.browser(launch_args=H.GPU_ARGS)
    try:
        with browser as page:
            page.set_default_timeout(30000)
            dialogs = []
            page.on('dialog', lambda dialog: (dialogs.append(dialog.type), dialog.dismiss()))
            H.open_editor(page, served, query='tier=low&test=1')
            H.choose_floor(page, f'{BID}:L1')
            yield page
            assert not dialogs, dialogs
            assert not H.unexpected(browser.errors), browser.errors
    finally:
        if browser._pw is not None and browser._b is None:
            browser._pw.stop()


def plan(page):
    return page.evaluate('window.__twin.plan')


def chair(page):
    return next(p for p in H.building(plan(page), BID)['items'] if p['id'] == CHAIR)


def menu(page):
    return page.locator('#editor-context-menu')


def tree_row(page, pid):
    page.click('#dock-tab-scene')
    host = page.locator('#scene-tree')
    row = host.locator(f'[data-scene-id="{pid}"]')

    def mount(locator):
        if not locator.count():
            host.get_by_role('treeitem').first.press('Home')
            for _ in range(120):
                H.settle(page, 2)
                if locator.count():
                    break
                box = host.bounding_box()
                assert box, 'Scene tree has no viewport'
                page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                page.mouse.wheel(0, max(36, box['height'] * .65))
        assert locator.count() == 1, f'Scene row is missing: {pid}'
        locator.scroll_into_view_if_needed()
        return locator

    if not row.count():
        # Open ancestors by real UI; choosing a floor need not expand its row.
        b = H.building(plan(page), BID)
        for parent in (host.locator(f'[data-scene-id="{BID}"]'),
                       host.locator(f'[data-floor="{BID}:L1"]').locator('..'),
                       host.locator(f'[data-scene-id="{b["rooms"][0]["id"]}"]')):
            parent = mount(parent)
            disclosure = parent.locator('[data-row-disclosure][aria-expanded="false"]')
            if disclosure.count():
                disclosure.click()
    return mount(row)


def choose_site(page):
    menu(page).get_by_role('menuitem', name='Move to', exact=True).click()
    with page.expect_response(lambda r: r.request.method == 'POST'
                              and r.url.split('?')[0].endswith('/api/house/editor/op')) as response:
        menu(page).get_by_role('menuitem', name='Site', exact=True).click()
    assert response.value.status == 200, response.value.text()
    page.wait_for_function('id => window.__twin.plan.site.furniture?.some(p => p.id === id)', arg=CHAIR)
    page.wait_for_function("id => window.__twinEditor.selectionStore.primary()?.pieceId === id && window.__twin.state.view === 'ext'", arg=CHAIR)
    H.settle(page, 3)


def scenario_move_item_to_site_and_undo():
    with editor() as page:
        before = chair(page)
        old = page.evaluate("""async ([bid,id]) => {
            const {hostPoint} = await import('../static/twin/twin_hosts.js');
            const {toLot} = await import('../static/twin/editor/lot_frame.js');
            const b=window.__twin.plan.buildings.find(b=>b.id===bid), p=b.items.find(p=>p.id===id);
            return {local:hostPoint(b,p.host,p.offset||0),lot:toLot(b,hostPoint(b,p.host,p.offset||0))};
        }""", [BID, CHAIR])
        x, y, z = old['local']
        H.look_down(page, BID, x, y, height=z + 30)
        # Find a real hit on the chair; never invoke the menu through a test hook.
        pixel = None
        for dx, dy, h in [(dx, dy, h) for h in (1, 2, .5) for dx in (0, -.5, .5) for dy in (0, -.5, .5)]:
            point = H.screen_of_world(page, x + dx, y + dy, z + h, BID)
            if page.evaluate('([x,y,id]) => window.__twin.pick(x,y)?.id === id', [*point, CHAIR]):
                pixel = point
                break
        assert pixel, 'no clickable chair pixel'
        H._on_canvas(page, *pixel)
        page.mouse.click(*pixel, button='right')
        choose_site(page)
        moved = next(p for p in plan(page)['site']['furniture'] if p['id'] == CHAIR)
        # Site pieces stand at a plan point [x, y]; the lot point also carries z.
        assert len(moved['at']) == 2 and math.dist(moved['at'], old['lot'][:2]) < .01, (old, moved)
        assert not any(p['id'] == CHAIR for p in H.building(plan(page), BID)['items'])
        members = page.evaluate('window.__twinEditor.selectionStore.members()')
        assert members == [{'kind': 'furniture', 'pieceId': CHAIR}], members
        for key in ('scale', 'tint', 'casts_shadow', 'object_kind', 'elevation'):
            assert moved[key] == before[key], key
        page.screenshot(path=str(SHOTS / 'move_to_site.png'))
        page.wait_for_function("!document.getElementById('rail-undo').disabled")
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.split('?')[0].endswith('/revert')) as response:
            page.keyboard.press('Control+z')
        assert response.value.status == 200, response.value.text()
        page.wait_for_function('([bid,id]) => window.__twin.plan.buildings.find(b=>b.id===bid).items.some(p=>p.id===id)', arg=[BID, CHAIR])
        assert chair(page) == before, (chair(page), before)
        assert not any(p['id'] == CHAIR for p in plan(page)['site'].get('furniture', []))


def scenario_hidden_piece_stays_hidden():
    with editor() as page:
        row = tree_row(page, CHAIR)
        row.get_by_role('button', name='Hide Reading chair', exact=True).click()
        row = tree_row(page, CHAIR)
        row.click(button='right')
        choose_site(page)
        row = tree_row(page, CHAIR)
        assert row.get_by_role('button', name='Show Reading chair', exact=True).get_attribute('aria-pressed') == 'true'
        page.screenshot(path=str(SHOTS / 'hidden_after_move.png'))


def scenario_locked_piece_stays_locked():
    with editor() as page:
        row = tree_row(page, CHAIR)
        row.get_by_role('button', name='Lock Reading chair', exact=True).click()
        row.click(button='right')
        choose_site(page)
        row = tree_row(page, CHAIR)
        assert row.get_by_role('button', name='Unlock Reading chair', exact=True).get_attribute('aria-pressed') == 'true'


def scenario_wall_piece_entry_disabled():
    with editor() as page:
        row = tree_row(page, WALL_ITEM)
        row.click(button='right')
        entry = menu(page).get_by_role('menuitem', name='Move to', exact=True)
        assert entry.is_disabled()
        reason = 'Wall and roof pieces stay on their wall or roof.'
        assert entry.get_attribute('title') == reason
        assert entry.get_attribute('aria-description') == reason
        page.screenshot(path=str(SHOTS / 'wall_move_disabled.png'))


if __name__ == '__main__':
    print(f'screenshots: {SHOTS}')
    scenarios = [scenario_move_item_to_site_and_undo, scenario_hidden_piece_stays_hidden,
                 scenario_locked_piece_stays_locked, scenario_wall_piece_entry_disabled]
    names = set(sys.argv[1:])
    H.run([s for s in scenarios if not names or s.__name__ in names])
