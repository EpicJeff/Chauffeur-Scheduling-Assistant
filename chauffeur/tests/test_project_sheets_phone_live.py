"""A project's piece in the phone's action sheet (front door spec §2, slice 2, Task 5).
Run from chauffeur/:  python tests/test_project_sheets_phone_live.py"""
from project_sheets_fixture import IDS, check, open_projects, pwa, serve, shot
from services import storage


def _projects_tab(page, served, who):
    page.set_viewport_size({'width': 390, 'height': 844})
    pwa(page, served, who)
    page.goto(served.url('app'), wait_until='load')
    page.wait_for_selector('#tab-more', state='visible', timeout=20000)
    open_projects(page)


def scenario_a_parent_opens_a_thread_and_a_program():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        _projects_tab(page, served, 'mom')
        page.wait_for_selector(f'[data-project-id="{IDS["bath"]}"]', timeout=15000)
        page.locator(f'[data-project-id="{IDS["bath"]}"]').first.click()
        page.wait_for_selector(f'[data-piece-open="thread:{IDS["thread"]}"]', timeout=10000)
        page.locator(f'[data-piece-open="thread:{IDS["thread"]}"]').click()
        page.wait_for_selector('[data-piece-sheet]', timeout=10000)
        text = page.locator('[data-piece-sheet]').inner_text()
        check('Tiler' in text and 'Add note' in text and 'Add a photo' in text, f"the thread's card with note and photo: {text[:300]}")
        shot(page, 'slice2-phone-thread')
        page.locator('[data-pwa-dismiss]').first.click()
        page.locator('[data-piece-open="program:pr-live"]').click()
        page.wait_for_selector('[data-piece-sheet]', timeout=10000)
        check('Strength basics' in page.locator('[data-piece-sheet]').inner_text(), "the phone's own program card")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_a_child_has_no_mission_to_open():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        _projects_tab(page, served, 'kid')
        page.wait_for_selector('[data-project-id="prj-bike"]', timeout=15000)
        page.locator('[data-project-id="prj-bike"]').first.click()
        page.wait_for_selector('[data-project-detail]', timeout=10000)
        check(page.locator('[data-piece-open^="mission:"]').count() == 0, "no mission for a child")


def scenario_no_tab_and_no_admin_anchor_in_sheets():
    served = serve()
    if served is None:
        return
    # The thread is about a program here, so its card carries an About line to tap.
    storage.update_thread(IDS['thread'], {'subject_kind': 'program', 'subject_id': 'pr-live', 'subject_rev': 1})
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        page.set_viewport_size({'width': 390, 'height': 844})
        pwa(page, served, 'mom')
        page.goto(served.url('app'), wait_until='load')
        page.wait_for_selector('#tab-more', state='visible', timeout=15000)
        check(page.locator('#tab-projects').count() == 0, "no Projects tab")
        page.locator('#tab-more').click()
        page.get_by_text('Projects', exact=True).first.click()
        page.wait_for_selector('[data-project-card]', timeout=15000)
        page.locator(f'[data-project-id="{IDS["bath"]}"]').click()
        page.wait_for_selector('[data-row]', timeout=10000)
        check(page.locator('#projects-container a[href]').count() == 0, "no anchors in the projects surface")
        check(page.locator('#tab-more').get_attribute('aria-current') == 'page', "More stays lit while Projects is open")
        page.locator(f'[data-row="conversation:{IDS["thread"]}"] [data-row-title]').click()
        page.wait_for_selector('[data-piece-sheet]', timeout=10000)
        hrefs = page.locator('[data-piece-sheet] a[href]').evaluate_all('els => els.map(e => e.getAttribute("href"))')
        check(all(h.startswith('http') and 'localhost' not in h for h in hrefs), f"no admin anchors inside the piece sheet: {hrefs}")
        shot(page, 'one-list-phone')
        # About: is a button that lands on the record's phone sheet, not an admin page.
        about = page.locator('[data-piece-sheet] [data-sit-nav="program:pr-live"]')
        check(about.count() == 1, f"the subject draws as a button: {page.locator('[data-piece-sheet]').inner_html()[:400]}")
        about.click()
        page.wait_for_function("() => (document.querySelector('[data-piece-sheet]') || {}).innerText?.includes('Strength basics')", timeout=10000)
        check('/app' in page.url, f"still on the phone app: {page.url}")
        check(served.errors() == [], f"no page errors: {served.errors()}")
    storage.update_thread(IDS['thread'], {'subject_kind': None, 'subject_id': None, 'subject_rev': 0})


def scenario_a_linked_list_opens_its_phone_home():
    served = serve()
    if served is None:
        return
    lst = storage.ensure_default_shopping_list()
    project = storage.get_project(IDS['bath'])
    storage.update_project(IDS['bath'], {'pieces': (project.get('pieces') or []) + [{'kind': 'list', 'id': lst['id'], 'added_by': 'mom'}]})
    try:
        with served.browser() as page:
            page.on('dialog', lambda d: d.dismiss())
            _projects_tab(page, served, 'mom')
            page.locator(f'[data-project-id="{IDS["bath"]}"]').first.click()
            row = page.locator(f'[data-row="link:{lst["id"]}"]')
            row.wait_for(timeout=10000)
            check(row.locator('a[href]').count() == 0, "a linked list's row is buttons only")
            row.locator('[data-row-title]').click()
            page.locator('[data-link-open]').click()
            page.wait_for_function("() => document.getElementById('chores-container').style.display === 'flex'"
                                   " && document.getElementById('chores-container').dataset.section === 'lists'", timeout=10000)
            check('/app' in page.url, f"the list opens in the phone app, not an admin page: {page.url}")
            check(page.evaluate('houseActiveListId') == lst['id'], "on that list")
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        storage.update_project(IDS['bath'], {'pieces': project.get('pieces') or []})


SCENARIOS = [scenario_a_parent_opens_a_thread_and_a_program, scenario_a_child_has_no_mission_to_open,
             scenario_no_tab_and_no_admin_anchor_in_sheets, scenario_a_linked_list_opens_its_phone_home]

if __name__ == "__main__":
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    raise SystemExit(1 if failed else 0)
