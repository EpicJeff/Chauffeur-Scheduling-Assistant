"""Task 4 Chromium acceptance. Claude runs this; Codex must not launch a browser.

Run from chauffeur/: python tests/test_house_editor_gutters_live.py
Uses the connected model harness, real card clicks, pointer drag and Ctrl+Z.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='gutters_live_')
sys.path.insert(0, str(Path(__file__).resolve().parent))
import house_editor_model_harness as H

BID = 'pool-house'
SHOTS = Path(os.environ.get('GUTTERS_REVIEW_OUTPUT') or tempfile.mkdtemp(prefix='gutters_editor_shots_'))


def fixture(plan):
    # The harness bridges this fixture into the connected model, including roofs.
    b = H.building(plan, BID)
    for section in b['roof']['sections']:
        section.pop('gutters', None)
        section.pop('downspouts', None)
    return plan


@contextmanager
def editor():
    served = H.serve(fixture)
    assert served is not None, 'Playwright is required'
    from services import twin_store
    twin_store.start_over()
    twin_store.push_round(fixture(H.household_plan()), 'build')
    browser = served.browser(launch_args=H.GPU_ARGS)
    try:
        with browser as page:
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


def frame_roof(page, rid):
    """Outside three-quarter view, including the wall drop and Properties card."""
    page.wait_for_function('window.__twin.ready')
    roof = page.evaluate("([bid,rid])=>window.__twin.plan.buildings.find(b=>b.id===bid).roofs.find(r=>r.id===rid)", [BID, rid])
    xs, ys = zip(*roof['area'])
    x, y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys), roof['plate'], 12)
    # Aim just to the right of the roof so it stays clear of the Properties dock.
    x, y = x + span * .18, y + span * .18
    H.look_at(page, BID, [x + span, y - span, roof['plate'] + span * .7],
              [x, y, roof['plate'] * .65])
    H.settle(page, 3)


def scenario_enable_gutters_drag_downspout_undo():
    with editor() as page:
        roof = page.evaluate("bid=>window.__twin.plan.buildings.find(b=>b.id===bid).roofs[0]", BID)
        rid = roof['id']
        # Use the shipped Scene tree helper to reveal ancestors and click the roof.
        from test_house_editor_move_to_live import tree_row
        tree_row(page, rid).locator('[data-scene-select]').click()
        card = page.locator('#piece-card')
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.split('?')[0].endswith('/editor/op')) as response:
            card.get_by_role('button', name='Gutters on all eaves', exact=True).click()
        assert response.value.status == 200, response.value.text()
        page.wait_for_function("([bid,rid])=>window.__twin.plan.buildings.find(b=>b.id===bid).roofs.find(r=>r.id===rid).edges.some(e=>e.gutter)", arg=[BID, rid])
        page.click('#dock-tab-scene')
        page.locator('#scene-floor-actions').get_by_role('button', name='All floors', exact=True).click()
        page.wait_for_function("window.__twin.ready && window.__twin.state.view === 'ext'")
        after_enable = page.evaluate("([bid,rid])=>window.__twin.plan.buildings.find(b=>b.id===bid).roofs.find(r=>r.id===rid)", [BID, rid])
        frame_roof(page, rid)
        handle = page.evaluate("window.__twinEditor.handles().find(h=>h.kind==='downspout')")
        assert handle, 'selected guttered roof must have a downspout handle'
        x, y, z = handle['at']
        start = H.screen_of_world(page, x, y, z, BID)
        end_points = [after_enable['area'][handle['edge']], after_enable['area'][(handle['edge'] + 1) % len(after_enable['area'])]]
        target = [a + .6 * (b - a) for a, b in zip(*end_points)]
        end = H.screen_of_world(page, *target, z, BID)
        SHOTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS / 'gutters-enabled.png'))
        H._on_canvas(page, *start)
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.split('?')[0].endswith('/editor/op')) as response:
            page.mouse.move(*start)
            page.mouse.down()
            page.mouse.move(*end, steps=12)
            page.mouse.up()
        assert response.value.status == 200, response.value.text()
        page.wait_for_function("([bid,rid,i])=>window.__twin.plan.buildings.find(b=>b.id===bid).roofs.find(r=>r.id===rid).edges[i].downspouts?.some(t=>Math.abs(t-.6)<.01)", arg=[BID, rid, handle['edge']])
        page.screenshot(path=str(SHOTS / 'downspout-dragged.png'))
        page.wait_for_function("!document.getElementById('rail-undo').disabled")
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.split('?')[0].endswith('/revert')) as response:
            page.keyboard.press('Control+z')
        assert response.value.status == 200, response.value.text()
        page.wait_for_function("([bid,rid,expected])=>JSON.stringify(window.__twin.plan.buildings.find(b=>b.id===bid).roofs.find(r=>r.id===rid).edges)===JSON.stringify(expected)", arg=[BID, rid, after_enable['edges']])
        page.screenshot(path=str(SHOTS / 'downspout-undo.png'))
        # Produce a real, inspectable gutter issue using the hand controls:
        # suppress every edge's outlets, then inspect the emergency-stub note.
        for index, edge in enumerate(after_enable['edges']):
            if not edge.get('gutter'):
                continue
            card.get_by_role('button', name=f'Edge {index + 1}:', exact=False).click()
            while card.get_by_role('button', name='Remove downspout', exact=False).count():
                before = card.get_by_role('button', name='Remove downspout', exact=False).count()
                with page.expect_response(lambda r: r.request.method == 'POST' and r.url.split('?')[0].endswith('/editor/op')) as response:
                    card.get_by_role('button', name='Remove downspout', exact=False).first.click()
                assert response.value.status == 200, response.value.text()
                page.wait_for_function("([bid,rid,i,n])=>window.__twin.plan.buildings.find(b=>b.id===bid).roofs.find(r=>r.id===rid).edges[i].downspouts?.length===n", arg=[BID, rid, index, before - 1])
                H.settle(page, 3)
            card.get_by_role('button', name='Back to roof', exact=True).click()
        # The Check walk opens from the "N things to check" count, not the build-pause step button.
        page.evaluate("document.getElementById('editor-flag-count').click()")
        check = page.locator('#check-card')
        check.wait_for(state='visible')
        for _ in range(100):
            if check.get_attribute('data-check-kind') == 'gutter':
                break
            check.get_by_role('button', name='Skip for now', exact=True).click()
        assert check.get_attribute('data-check-kind') == 'gutter', 'no gutter issue in Check'
        assert check.locator('[data-gutter-check]').count() > 0
        assert check.get_by_role('button', name='Looks fine', exact=True).is_visible()
        frame_roof(page, rid)
        page.screenshot(path=str(SHOTS / 'gutter-check-list.png'))


if __name__ == '__main__':
    print(f'screenshots: {SHOTS}')
    H.run([scenario_enable_gutters_drag_downspout_undo])
