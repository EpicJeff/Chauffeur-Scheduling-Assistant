"""A project's piece in the phone's action sheet (front door spec §2, slice 2, Task 5).
Run from chauffeur/:  python tests/test_project_sheets_phone_live.py"""
from project_sheets_fixture import IDS, check, pwa, serve, shot


def _projects_tab(page, served, who):
    page.set_viewport_size({'width': 390, 'height': 844})
    pwa(page, served, who)
    page.goto(served.url('app'), wait_until='load')
    page.wait_for_selector('#tab-projects', timeout=20000)
    page.locator('#tab-projects').click()


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


SCENARIOS = [scenario_a_parent_opens_a_thread_and_a_program, scenario_a_child_has_no_mission_to_open]

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
