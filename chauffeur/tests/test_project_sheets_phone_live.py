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


# A sheet's anchors may leave the app (a source, a booking page) or fetch its
# media (api/...); none may land on an admin page of this app.
ADMIN_HREFS = """(els) => els.map(e => e.href).filter(h => {
    const u = new URL(h, location.href);
    return u.origin === location.origin && !/^\/(api|app)(\/|$)/.test(u.pathname);
})"""


def _admin_hrefs(page):
    return page.locator('[data-piece-sheet] a[href]').evaluate_all(ADMIN_HREFS)


def scenario_no_tab_and_no_admin_anchor_in_sheets():
    served = serve()
    if served is None:
        return
    # The thread is about a program here, so its card carries an About line to tap.
    storage.update_thread(IDS['thread'], {'subject_kind': 'program', 'subject_id': 'pr-live', 'subject_rev': 1})
    try:
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
            page.wait_for_function("() => (document.querySelector('[data-piece-sheet]') || {}).innerText?.includes('Tiler')", timeout=10000)
            check(_admin_hrefs(page) == [], f"no admin anchors inside the thread sheet: {_admin_hrefs(page)}")
            shot(page, 'one-list-phone')
            # About: is a button that lands on the record's phone sheet, not an admin page.
            about = page.locator('[data-piece-sheet] [data-sit-nav="program:pr-live"]')
            check(about.count() == 1, f"the subject draws as a button: {page.locator('[data-piece-sheet]').inner_html()[:400]}")
            about.click()
            page.wait_for_function("() => (document.querySelector('[data-piece-sheet]') || {}).innerText?.includes('Strength basics')", timeout=10000)
            check('/app' in page.url, f"still on the phone app: {page.url}")
            check(_admin_hrefs(page) == [], f"no admin anchors inside the program sheet: {_admin_hrefs(page)}")
            page.locator('[data-pwa-dismiss]').first.click()
            page.wait_for_selector('[data-piece-sheet]', state='detached', timeout=10000)
            page.locator(f'[data-row="argyle:{IDS["mission"]}"] [data-row-title]').click()
            page.wait_for_function("() => (document.querySelector('[data-piece-sheet]') || {}).innerText?.includes('Which day suits the tiler?')", timeout=10000)
            check(_admin_hrefs(page) == [], f"no admin anchors inside the mission sheet: {_admin_hrefs(page)}")
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        storage.update_thread(IDS['thread'], {'subject_kind': None, 'subject_id': None, 'subject_rev': 0})


def scenario_a_project_opens_only_through_its_door():
    """phoneOpenRecord('project') and chfPwaOpenProjects open Projects only for
    someone More offers it to: a helper is told where to find it instead; a
    sprout lands on More, where its projects live in their own slot."""
    served = serve()
    if served is None:
        return
    if not storage.get_member('helper'):
        storage.add_member({'id': 'helper', 'name': 'Nana', 'role': 'helper', 'color_code': '#7a5a28'})
    token = storage.create_member_token('helper')
    with served.browser() as page:
        page.set_viewport_size({'width': 390, 'height': 844})
        page.goto(served.url('api/account/setup'))
        page.evaluate('(s) => { localStorage.clear(); for (const [k, v] of Object.entries(s)) localStorage.setItem(k, v); }',
                      {'chauffeur_member_id': 'helper', 'chauffeur_member_token': token, 'chauffeur_member_token_for': 'helper'})
        page.goto(served.url('app'), wait_until='load')
        page.wait_for_function("() => typeof window.phoneOpenRecord === 'function' && currentMemberRole() === 'helper'", timeout=15000)
        before = page.evaluate('currentView')
        check(before != 'projects', f"a helper does not start on Projects: {before}")
        # A helper's page draws 403s on load for doors their role does not hold
        # (chores, settings); what the guard prevents is the Projects view and its open.
        page.evaluate("() => { window._opens = 0; for (const e of ['chf-project-open', 'chf-projects-open'])"
                      " window.addEventListener(e, () => window._opens++); }")
        for call in ("window.phoneOpenRecord('project', 'prj-bath')", "window.chfPwaOpenProjects()"):
            page.evaluate('() => { const el = document.getElementById("global-alert"); if (el) el.textContent = ""; }')
            answer = page.evaluate(f'() => {call}')
            check(page.evaluate('currentView') == before, f"{call} leaves a helper where they were: {page.evaluate('currentView')}")
            page.wait_for_function("() => (document.getElementById('global-alert') || {}).textContent?.includes('projects page on a computer')",
                                   timeout=5000)   # it says where to find it
            if 'chfPwaOpenProjects' in call:
                check(answer is False, f"chfPwaOpenProjects answers false: {answer}")
        check(page.evaluate('window._opens') == 0, "nothing opens Projects for a helper")
    original = storage.get_member('kid').get('stage_override')
    storage.update_member('kid', {'stage_override': 'sprout'})
    try:
        with served.browser() as page:
            page.set_viewport_size({'width': 390, 'height': 844})
            pwa(page, served, 'kid')
            page.goto(served.url('app'), wait_until='load')
            page.wait_for_function("() => typeof window.phoneOpenRecord === 'function' && pwaChildStage() === 'sprout'", timeout=15000)
            loaded = len(served.errors())   # a sprout's page 403s on api/settings at load
            page.evaluate("() => window.phoneOpenRecord('project', 'prj-bike')")
            page.wait_for_selector('#pwa-sprout-projects [data-project-detail]', state='visible', timeout=10000)
            check(page.evaluate('currentView') == 'more', f"a sprout's project opens in More: {page.evaluate('currentView')}")
            check(served.errors()[loaded:] == [], f"no page errors from the call: {served.errors()[loaded:]}")
    finally:
        storage.update_member('kid', {'stage_override': original})


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
             scenario_no_tab_and_no_admin_anchor_in_sheets, scenario_a_project_opens_only_through_its_door,
             scenario_a_linked_list_opens_its_phone_home]

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
