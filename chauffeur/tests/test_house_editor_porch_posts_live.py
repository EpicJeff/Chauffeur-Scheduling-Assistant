"""Live Chromium check for porch posts editor UI.

Selects a post from Scene, inspects the porch Posts section and post card,
drags the post handle, adds a post and deletes a post, intercepting and
asserting every operation sent to /editor/op.
"""
from contextlib import contextmanager
import copy
import json
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
    # Prefer pool-house porch if it has posts (nice clean framing), else first porch with >= 2 posts.
    for prefer in ('pool-house', None):
        for b in plan.get('buildings') or []:
            if prefer and b['id'] != prefer:
                continue
            for p in b.get('porches') or []:
                if len(p.get('columns') or []) >= 2:
                    return b['id'], p
    raise AssertionError('No porch with at least 2 posts found in household fixture')


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
            yield page
            assert not dialogs, dialogs
            assert not H.unexpected(browser.errors), browser.errors
    finally:
        if browser._pw is not None and browser._b is None:
            browser._pw.stop()


def frame_post(page, bid, at, z):
    x, y = at
    H.look_at(page, bid, [x + 8, y - 9, z + 6.5], [x + 1.2, y, z + 2.0])
    H.settle(page, 4)


def scenario_porch_posts_scene_drag_add_delete():
    SHOTS.mkdir(parents=True, exist_ok=True)
    with editor() as page:
        plan = page.evaluate('window.__twin.plan')
        bid, porch = find_porch_with_posts(plan)
        porch_id = porch['id']
        level_id = porch.get('level') or 'L1'
        H.choose_floor(page, f'{bid}:{level_id}')
        page.locator('#scene-floor-actions').get_by_role('button', name='All floors', exact=True).click()
        page.wait_for_function("window.__twin.ready && window.__twin.state.view === 'ext'")

        # Intercept /editor/op for the three new post operations (server half is on the other branch).
        sent = []
        round_counter = [100]
        live_plan = [copy.deepcopy(page.evaluate('window.__twin.plan'))]

        def apply_mock_post_op(op_data):
            p = copy.deepcopy(live_plan[0])
            b = next(x for x in p['buildings'] if x['id'] == op_data['building'])
            po = next(x for x in b['porches'] if x['id'] == op_data['porch'])
            cols = po.setdefault('columns', [])
            # Mint ids on first post operation (same contract as spec).
            if any('id' not in c for c in cols):
                for idx, c in enumerate(cols):
                    c.setdefault('id', f'post:live{idx}')
            def find_col(ref):
                for idx, c in enumerate(cols):
                    if c.get('id') == ref or f'post:{po["id"]}:{idx}' == ref:
                        return idx
                return -1
            kind = op_data['op']
            if kind == 'update_porch_post':
                idx = find_col(op_data['post'])
                if idx >= 0:
                    if 'at' in op_data:
                        cols[idx]['at'] = op_data['at']
                    if 'size' in op_data:
                        cols[idx]['size'] = op_data['size']
            elif kind == 'add_porch_post':
                cols.append({'id': f'post:live{len(cols)}', 'at': list(cols[0]['at']), 'size': cols[0].get('size', 0.5)})
            elif kind == 'delete_porch_post':
                idx = find_col(op_data['post'])
                if idx >= 0:
                    cols.pop(idx)
            live_plan[0] = p
            round_counter[0] += 1
            return {'round': round_counter[0], 'plan': p, 'model': p, 'words': f'Applied {kind}.'}

        def handle_op(route):
            if route.request.method == 'POST':
                body = route.request.post_data_json
                op_data = body.get('op') if isinstance(body.get('op'), dict) else body
                if op_data.get('op') in ('update_porch_post', 'add_porch_post', 'delete_porch_post'):
                    sent.append(op_data)
                    payload = apply_mock_post_op(op_data)
                    route.fulfill(status=200, content_type='application/json', body=json.dumps(payload))
                    return
            route.continue_()

        page.route('**/editor/op', handle_op)
        try:
            # 1. Select porch in Scene, expand it to see Post 1..N, capture Scene + Porch Posts section.
            host = page.locator('#scene-tree')
            porch_row = tree_row(page, bid, level_id, porch_id)
            porch_row.locator('[data-scene-select]').click()
            disc = porch_row.locator('[data-row-disclosure]')
            if disc.get_attribute('aria-expanded') != 'true':
                disc.click()
            H.settle(page, 2)
            post0_ref = f'post:{porch_id}:0'
            post1_ref = f'post:{porch_id}:1'
            post0_row = mount_row(page, host, host.locator(f'[data-scene-id="{post0_ref}"]'), post0_ref)
            post1_row = mount_row(page, host, host.locator(f'[data-scene-id="{post1_ref}"]'), post1_ref)
            H.settle(page, 2)
            assert post0_row.is_visible()
            assert post1_row.is_visible()

            card = page.locator('#piece-card')
            posts_section = card.locator('[data-porch-posts]')
            posts_section.wait_for(state='visible')
            assert f'{len(porch["columns"])} posts' in posts_section.locator('[data-porch-posts-count]').inner_text()
            page.screenshot(path=str(SHOTS / 'scene-tree-posts.png'))
            posts_section.scroll_into_view_if_needed()
            H.settle(page, 2)
            page.screenshot(path=str(SHOTS / 'porch-card-posts.png'))

            # 2. Select Post 2 from Scene tree, verify card & breadcrumb, capture post card.
            post1_row.locator('[data-scene-select]').click()
            H.settle(page, 3)
            assert 'Post 2' in card.locator('h3').inner_text()
            assert '> Post 2' in page.locator('#properties-crumbs').inner_text()
            assert card.locator('input[aria-label="Position X (ft)"]').is_visible()
            assert card.locator('input[aria-label="Position Y (ft)"]').is_visible()
            assert card.locator('input[aria-label="Size (ft)"]').is_visible()
            assert card.locator('[data-post-material-note]').is_visible()
            page.screenshot(path=str(SHOTS / 'post-card.png'))

            # 3. Frame the selected post close up, verify handle is visible, capture close-up shot.
            handle = page.evaluate("window.__twinEditor.handles().find(h => h.kind === 'porch_post')")
            assert handle, 'selected porch_post must expose a porch_post handle'
            frame_post(page, bid, handle['at'][:2], handle['at'][2])
            handle_node = page.locator('.editor-handle-porch_post')
            handle_node.wait_for(state='visible')
            page.screenshot(path=str(SHOTS / 'post-handle-closeup.png'))

            # 4. Drag the post handle -> assert one update_porch_post sent!
            x, y, z = handle['at']
            start = H.screen_of_world(page, x, y, z, bid)
            end = H.screen_of_world(page, x + 2.0, y, z, bid)
            H._on_canvas(page, *start)
            page.mouse.move(*start)
            page.mouse.down()
            page.mouse.move(*end, steps=10)
            page.mouse.up()
            page.wait_for_function('() => true')
            H.settle(page, 4)
            assert len(sent) == 1, f'expected 1 op after drag, got {sent}'
            assert sent[0]['op'] == 'update_porch_post', sent[0]
            assert sent[0]['building'] == bid and sent[0]['porch'] == porch_id and sent[0]['post'] == post1_ref, sent[0]
            assert abs(sent[0]['at'][0] - x) > 0.5, sent[0]

            # 5. Select the porch, click Add post -> assert add_porch_post sent!
            card.locator('[data-select-porch]').click()
            H.settle(page, 2)
            card.locator('[data-porch-posts]').get_by_role('button', name='Add post', exact=True).click()
            H.settle(page, 4)
            assert len(sent) == 2, f'expected 2 ops after add, got {sent}'
            assert sent[1] == {'op': 'add_porch_post', 'building': bid, 'porch': porch_id}, sent[1]

            # 6. Delete the selected post -> assert delete_porch_post sent!
            card.get_by_role('button', name='Delete', exact=True).click()
            confirm = page.locator('#cc-confirm-modal')
            confirm.wait_for(state='visible')
            confirm.get_by_role('button', name='Delete', exact=True).click()
            H.settle(page, 4)
            assert len(sent) == 3, f'expected 3 ops after delete, got {sent}'
            assert sent[2]['op'] == 'delete_porch_post', sent[2]
            assert sent[2]['building'] == bid and sent[2]['porch'] == porch_id, sent[2]
            assert sent[2]['post'], sent[2]
            assert not page.locator('#cc-alert-modal').is_visible(), 'Delete raised an error alert'
        finally:
            page.unroute('**/editor/op', handle_op)


if __name__ == '__main__':
    print(f'screenshots: {SHOTS}')
    H.run([scenario_porch_posts_scene_drag_add_delete])
