"""Live Chromium check for porch posts editor UI against the REAL server.

Tests plain porch selection by 3D canvas click (no rebuild, no focus), selecting
a post by 3D canvas click, dragging its handle, undoing the drag, multi-selecting
two posts with the Move gizmo, adding a post and deleting a post — asserting saved
results in the real backend model and capturing refreshed screenshots.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import sys
import tempfile

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='porch_posts_live_')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT))
import house_editor_model_harness as H

SHOTS = Path(os.environ.get('PORCH_POSTS_SHOTS') or (ROOT.parent / '.gemini-tmp' / 'shots'))


def mount_row(page, host, row, label='row'):
    if not row.count():
        host.get_by_role('treeitem').first.press('Home')
        for _ in range(160):
            H.settle(page, 2)
            if row.count():
                break
            box = host.bounding_box()
            assert box, 'Scene tree has no viewport'
            page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
            page.mouse.wheel(0, max(36, box['height'] * .65))
    assert row.count() == 1, f'Scene row is missing: {label}'
    row.scroll_into_view_if_needed()
    return row


def tree_row(page, bid, level_id, pid):
    page.click('#dock-tab-scene')
    host = page.locator('#scene-tree')
    for parent_loc, label in (
        (host.locator(f'[data-scene-id="{bid}"]'), bid),
        (host.locator(f'[data-floor="{bid}:{level_id}"]').locator('..'), f'{bid}:{level_id}'),
    ):
        parent = mount_row(page, host, parent_loc, label)
        disclosure = parent.locator('[data-row-disclosure][aria-expanded="false"]')
        if disclosure.count():
            disclosure.click()
            H.settle(page, 2)
    return mount_row(page, host, host.locator(f'[data-scene-id="{pid}"]'), pid)


def find_porch_with_posts(plan):
    for prefer in ('pool-house', None):
        for b in plan.get('buildings') or []:
            if prefer and b['id'] != prefer:
                continue
            for p in b.get('porches') or []:
                if len(p.get('columns') or []) >= 2:
                    return b['id'], p
    raise AssertionError('No porch with at least 2 posts found in household fixture')


def saved_columns(bid, porch_id):
    from services import twin_store
    twin_store._invalidate_reads()
    model = twin_store.current_model()
    b = next(x for x in model['buildings'] if x['id'] == bid)
    detail = next(p for p in b.get('porches_detail') or [] if p['id'] == porch_id)
    return detail.get('columns') or []


def wait_saved(page, rounds_before, timeout=20000):
    page.wait_for_function(
        """(n) => {
            const state = document.getElementById('editor-save-state')?.textContent?.trim();
            return state === 'Saved' && window.__editor?.roundCount?.() > n;
        }""",
        arg=rounds_before,
        timeout=timeout,
    )
    H.settle(page, 3)


@contextmanager
def editor():
    served = H.serve()
    assert served is not None, 'Playwright is required'
    from services import twin_store
    twin_store.start_over()
    twin_store.push_round(H.household_plan(), 'build')
    browser = served.browser(launch_args=H.GPU_ARGS)
    try:
        with browser as page:
            page.set_default_timeout(30000)
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.type), d.dismiss()))
            H.open_editor(page, served, query='tier=low&test=1')
            page.evaluate("""() => {
                const v = window.__twin, orig = v.rebuild.bind(v);
                window.__postRebuildProbe = 0;
                v.rebuild = (...args) => { window.__postRebuildProbe++; return orig(...args); };
            }""")
            yield page
            assert not dialogs, dialogs
            assert not H.unexpected(browser.errors), browser.errors
    finally:
        if browser._pw is not None and browser._b is None:
            browser._pw.stop()


def frame_post(page, bid, at, z):
    x, y = at
    H.look_at(page, bid, [x + 8, y - 9, z + 6.5], [x + 1.2, y, z + 2.5])
    H.settle(page, 4)


def frame_two_posts(page, bid, p0, p1, z):
    mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    span = max(8.0, ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5 * 1.4)
    H.look_at(page, bid, [mx + span * 0.65, my - span * 0.85, z + span * 0.7], [mx, my, z + 2.5])
    H.settle(page, 4)


def find_post_click_pixel(page, bid, post_id, at, z):
    for dz in (3.0, 4.5, 2.0, 6.0, 1.0):
        px = H.screen_of_world(page, at[0], at[1], z + dz, bid)
        hit = page.evaluate("""([x, y, pid, bid]) => {
            const r = window.__twin.renderer3.domElement.getBoundingClientRect();
            for (const dx of [0, -4, 4, -8, 8]) for (const dy of [0, -4, 4, -8, 8]) {
                const cx = x + dx, cy = y + dy;
                if (cx < r.left + 4 || cx > r.right - 4 || cy < r.top + 4 || cy > r.bottom - 4) continue;
                const h = window.__twin.pick(cx, cy);
                if (h && h.kind === 'porch_post' && h.id === pid && h.building === bid) return [cx, cy];
            }
            return null;
        }""", [px[0], px[1], post_id, bid])
        if hit:
            return hit
    return None


def scenario_porch_posts_real_server_live():
    SHOTS.mkdir(parents=True, exist_ok=True)
    with editor() as page:
        plan = page.evaluate('window.__twin.plan')
        bid, porch = find_porch_with_posts(plan)
        porch_id = porch['id']
        level_id = porch.get('level') or 'L1'
        initial_count = len(porch['columns'])
        post0_ref = f'post:{porch_id}:0'
        post1_ref = f'post:{porch_id}:1'

        # 1. Select the porch by clicking it in the 3D scene -> plain selection, ZERO rebuilds!
        H.choose_floor(page, f'{bid}:{level_id}')
        page.evaluate('key => window.__twin.setTopCamera(key)', f'{bid}:{level_id}')
        H.settle(page, 4)
        porch_pixel = page.evaluate("""({bid, rid, level}) => {
            const v = window.__twin, r = v.plan.buildings.find(b => b.id === bid).rooms.find(r => r.id === rid);
            const xs = r.polygon.map(p => p[0]), ys = r.polygon.map(p => p[1]);
            for (let i = 1; i < 10; i++) for (let j = 1; j < 10; j++) {
                const x = Math.min(...xs) + (Math.max(...xs) - Math.min(...xs)) * i / 10;
                const y = Math.min(...ys) + (Math.max(...ys) - Math.min(...ys)) * j / 10;
                const px = v.screenOfFloor(x, y, `${bid}:${level}`), hit = v.pick(...px);
                if (hit?.id === rid && hit.building === bid) return px;
            }
            return null;
        }""", dict(bid=bid, rid=porch_id, level=level_id))
        assert porch_pixel, 'no unobscured porch floor pixel for real canvas click'
        rebuilds_before = page.evaluate('window.__postRebuildProbe')
        page.mouse.click(*porch_pixel)
        H.settle(page, 3)
        sel = page.evaluate('window.__twinEditor.selection()')
        assert sel['id'] == porch_id and sel['room'] is None, f'plain porch click must not focus: {sel}'
        assert page.evaluate('window.__postRebuildProbe') == rebuilds_before, 'plain porch click must not rebuild'

        # Expand porch in Scene, verify Post 1..N and porch card Posts section, capture Scene + Porch shots.
        host = page.locator('#scene-tree')
        porch_row = tree_row(page, bid, level_id, porch_id)
        disc = porch_row.locator('[data-row-disclosure]')
        if disc.get_attribute('aria-expanded') != 'true':
            disc.click()
        H.settle(page, 2)
        post0_row = mount_row(page, host, host.locator(f'[data-scene-id="{post0_ref}"]'), post0_ref)
        post1_row = mount_row(page, host, host.locator(f'[data-scene-id="{post1_ref}"]'), post1_ref)
        H.settle(page, 2)
        assert post0_row.is_visible() and post1_row.is_visible()

        card = page.locator('#piece-card')
        posts_section = card.locator('[data-porch-posts]')
        posts_section.wait_for(state='visible')
        assert f'{initial_count} posts' in posts_section.locator('[data-porch-posts-count]').inner_text()
        page.screenshot(path=str(SHOTS / 'scene-tree-posts.png'))
        posts_section.scroll_into_view_if_needed()
        H.settle(page, 2)
        page.screenshot(path=str(SHOTS / 'porch-card-posts.png'))

        # 2. Switch to All floors and select Post 2 by clicking it directly in the 3D scene!
        page.locator('#scene-floor-actions').get_by_role('button', name='All floors', exact=True).click()
        page.wait_for_function("window.__twin.ready && window.__twin.state.view === 'ext'")
        # Re-select porch plainly first so ext-view click picks the post directly rather than building.
        porch_row = mount_row(page, host, host.locator(f'[data-scene-id="{porch_id}"]'), porch_id)
        porch_row.locator('[data-scene-select]').click()
        H.settle(page, 2)
        post1_at = porch['columns'][1]['at']
        level_elev = next(
            (l.get('elevation', 0) for b in plan['buildings'] if b['id'] == bid for l in b['levels'] if l['id'] == level_id),
            0,
        )
        post_z = porch.get('floor', level_elev)
        frame_post(page, bid, post1_at, post_z)
        post_pixel = find_post_click_pixel(page, bid, post1_ref, post1_at, post_z)
        assert post_pixel, 'could not find clickable 3D pixel on Post 2'
        rebuilds_before = page.evaluate('window.__postRebuildProbe')
        page.mouse.click(*post_pixel)
        H.settle(page, 3)
        sel_post = page.evaluate('window.__twinEditor.selection()')
        assert sel_post['kind'] == 'porch_post' and sel_post['id'] == post1_ref, sel_post
        assert page.evaluate('window.__postRebuildProbe') == rebuilds_before, 'clicking post must not rebuild'
        assert 'Post 2' in card.locator('h3').inner_text()
        assert '> Post 2' in page.locator('#properties-crumbs').inner_text()
        close_btn = card.locator('button[aria-label="Close piece card"]')
        x_input = card.locator('input[aria-label="Position X (ft)"]')
        assert close_btn.is_visible() and x_input.is_visible()
        close_box, x_box = close_btn.bounding_box(), x_input.bounding_box()
        assert close_box['y'] + close_box['height'] <= x_box['y'] + 1, (close_box, x_box)
        page.screenshot(path=str(SHOTS / 'post-card.png'))

        # 3. Capture selected post close-up (verify handle + visual outline/tint inspection).
        handle = page.evaluate("window.__twinEditor.handles().find(h => h.kind === 'porch_post')")
        assert handle, 'selected porch_post must expose a porch_post handle'
        page.locator('.editor-handle-porch_post').wait_for(state='visible')
        page.screenshot(path=str(SHOTS / 'post-handle-closeup.png'))

        # 4. Drag Post 2's handle -> assert REAL server saved it -> UNDO -> assert original position restored!
        orig_at = list(saved_columns(bid, porch_id)[1]['at'])
        rounds = page.evaluate('window.__editor.roundCount()')
        x, y, z = handle['at']
        start = H.screen_of_world(page, x, y, z, bid)
        end = H.screen_of_world(page, x + 2.0, y, z, bid)
        H._on_canvas(page, *start)
        page.mouse.move(*start)
        page.mouse.down()
        page.mouse.move(*end, steps=10)
        page.mouse.up()
        wait_saved(page, rounds)
        cols_after_drag = saved_columns(bid, porch_id)
        assert len(cols_after_drag) == initial_count
        assert cols_after_drag[1]['id'] == post1_ref
        assert abs(cols_after_drag[1]['at'][0] - orig_at[0]) > 0.5, cols_after_drag[1]

        rounds = page.evaluate('window.__editor.roundCount()')
        page.click('#rail-undo')
        wait_saved(page, rounds)
        cols_after_undo = saved_columns(bid, porch_id)
        assert abs(cols_after_undo[1]['at'][0] - orig_at[0]) < 1e-4, (cols_after_undo[1], orig_at)
        assert abs(cols_after_undo[1]['at'][1] - orig_at[1]) < 1e-4, (cols_after_undo[1], orig_at)
        assert page.evaluate('window.__twinEditor.selection().id') == post1_ref

        # 5. Multi-select Post 1 and Post 2 with Move gizmo visible, capture two-posts-gizmo.png!
        post0_row = mount_row(page, host, host.locator(f'[data-scene-id="{post0_ref}"]'), post0_ref)
        post0_row.locator('[data-scene-select]').click(modifiers=['Control'])
        H.settle(page, 2)
        members = page.evaluate('window.__twinEditor.members()')
        assert len(members) == 2 and all(m['kind'] == 'porch_post' for m in members), members
        assert '2 posts' in card.locator('[data-selection-summary]').inner_text()
        page.click('#rail-move')
        frame_two_posts(page, bid, cols_after_undo[0]['at'], cols_after_undo[1]['at'], z)
        gizmo_handles = page.evaluate("window.__twinEditor.handles().filter(h => h.kind && h.kind.startsWith('gizmo_'))")
        assert len(gizmo_handles) >= 2, gizmo_handles
        page.screenshot(path=str(SHOTS / 'two-posts-gizmo.png'))
        page.click('#rail-select')

        # 6. Select the porch, click Add post -> assert REAL server added it and editor selected it!
        porch_row = mount_row(page, host, host.locator(f'[data-scene-id="{porch_id}"]'), porch_id)
        porch_row.locator('[data-scene-select]').click()
        H.settle(page, 2)
        rounds = page.evaluate('window.__editor.roundCount()')
        card.locator('[data-porch-posts]').get_by_role('button', name='Add post', exact=True).click()
        wait_saved(page, rounds)
        cols_after_add = saved_columns(bid, porch_id)
        assert len(cols_after_add) == initial_count + 1, cols_after_add
        added_id = cols_after_add[-1]['id']
        assert page.evaluate('window.__twinEditor.selection().id') == added_id

        # 7. Delete the added post -> assert "Delete this post?", REAL server removed it, plain porch selection (no focus)!
        rounds = page.evaluate('window.__editor.roundCount()')
        card.get_by_role('button', name='Delete', exact=True).click()
        confirm = page.locator('#cc-confirm-modal')
        confirm.wait_for(state='visible')
        assert 'Delete this post?' in confirm.inner_text()
        confirm.get_by_role('button', name='Delete', exact=True).click()
        wait_saved(page, rounds)
        cols_after_del = saved_columns(bid, porch_id)
        assert len(cols_after_del) == initial_count, cols_after_del
        sel_after_del = page.evaluate('window.__twinEditor.selection()')
        assert sel_after_del['id'] == porch_id and sel_after_del['room'] is None, sel_after_del
        assert not page.locator('#cc-alert-modal').is_visible(), 'Delete raised an error alert'


if __name__ == '__main__':
    print(f'screenshots: {SHOTS}')
    H.run([scenario_porch_posts_real_server_live])
