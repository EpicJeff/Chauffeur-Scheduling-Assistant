"""The Projects page: lanes, a project's detail with its pieces, Add a piece
(front door spec §2, slice 2, Task 2). Run from chauffeur/:
python tests/test_projects_detail_live.py   (PROJECTS_SHOTS=<dir> for screenshots)"""
from project_sheets_fixture import IDS, admin, check, pwa, serve, shot, storage


def _opened(page):
    return page.evaluate("() => { const out = []; window.addEventListener('chf-record-sheet-open', e => out.push(e.detail)); window.__sheets = out; }")


def scenario_lanes_and_the_programs_filter():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects'), wait_until='load')
        page.wait_for_selector('[data-lane="needs_you"]', timeout=15000)
        needs = page.locator('[data-lane="needs_you"]').inner_text()
        check('Ride a bike' in needs and 'Bathroom' in needs, f"Kate's unplanned project and the program to approve: {needs}")
        check('Needs a plan' in needs, "the card says what it needs")
        check(not any('0 of 0 done' in text for text in page.locator('[data-project-card]').all_inner_texts()),
              "an empty project has no zero-step progress line")
        page.locator('[data-lane-filter="programs"]').click()
        body = page.locator('[data-lane]').all_inner_texts()
        check(any('Bathroom' in t for t in body) and not any('Ride a bike' in t for t in body), f"Programs filter: {body}")
        shot(page, 'slice2-lanes')
        page.goto(served.url('projects?lane=programs'), wait_until='load')
        page.wait_for_selector('[data-lane-filter="programs"][aria-pressed="true"]', timeout=10000)
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_the_detail_view_and_its_pieces():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects'), wait_until='load')
        page.wait_for_selector(f'[data-project-id="{IDS["bath"]}"]', timeout=15000)
        page.locator(f'[data-project-id="{IDS["bath"]}"]').first.click()
        page.wait_for_selector('[data-project-detail]', timeout=10000)
        check('id=' + IDS['bath'] in page.url, f"the address names the project: {page.url}")
        for key in (f'thread:{IDS["thread"]}', f'mission:{IDS["mission"]}', 'program:pr-prop', 'program:pr-live'):
            check(page.locator(f'[data-piece="{key}"]').count() == 1, f"a card for {key}")
            check(page.locator(f'[data-piece-open="{key}"]').count() == 1, f"Open on {key}")
            action = page.locator(f'[data-piece-open="{key}"]')
            check(action.evaluate("el => el.parentElement.classList.contains('justify-end')"),
                  f"Open belongs to a right-aligned card action row: {key}")
            if key.startswith('program:'):
                check(page.locator(f'[data-piece="{key}"] .bg-gray-900 [data-piece-open]').count() == 1,
                      f"Open is inside the program card: {key}")
        check('Tiler' in page.locator(f'[data-piece="thread:{IDS["thread"]}"]').inner_text(), "the thread's situation card")
        _opened(page)
        page.locator(f'[data-piece-open="thread:{IDS["thread"]}"]').click()
        sheets = page.evaluate('() => window.__sheets')
        check(sheets and sheets[0]['kind'] == 'thread' and sheets[0]['id'] == IDS['thread'] and sheets[0]['projectId'] == IDS['bath'],
              f"Open asks for the sheet: {sheets}")
        shot(page, 'slice2-detail')
        page.locator('[data-project-back]').click()
        page.wait_for_selector(f'[data-project-id="{IDS["bath"]}"]', timeout=10000)
        check('id=' not in page.url, f"back drops the project from the address: {page.url}")
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-project-detail]', timeout=10000)
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_add_a_piece_inside_the_project():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-add-piece]', timeout=15000)
        page.locator('[data-add-piece]').click()
        page.locator('[data-prompt-choice]', has_text='A conversation with someone outside').first.click()
        form = page.locator('[data-piece-form="thread"]')
        form.locator('input[name="title"]').fill('Plumber')
        form.locator('input[name="counterparty_name"]').fill('Bob Pipes')
        form.locator('[data-piece-create]').click()
        for _ in range(40):
            rows = [t for t in storage.get_threads() if t.get('title') == 'Plumber']
            if rows and rows[0].get('project_id'):
                break
            page.wait_for_timeout(250)
        check(rows and rows[0]['project_id'] == IDS['bath'] and rows[0]['counterparty_name'] == 'Bob Pipes', f"made inside: {rows}")
        page.wait_for_selector(f'[data-piece="thread:{rows[0]["id"]}"]', timeout=10000)
        page.locator('[data-add-piece]').click()
        page.locator('[data-prompt-choice]', has_text='Work for Argyle').first.click()
        form = page.locator('[data-piece-form="mission"]')
        form.locator('textarea[name="goal"]').fill('Compare three plumbers')
        form.locator('select[name="tier"]').select_option('flash')
        form.locator('[data-piece-create]').click()
        for _ in range(40):
            ms = [m for m in storage.get_missions() if m.get('goal') == 'Compare three plumbers']
            if ms and ms[0].get('project_id'):
                break
            page.wait_for_timeout(250)
        check(ms and ms[0]['project_id'] == IDS['bath'] and ms[0]['tier'] == 'flash', f"launched inside, Flash kept: {ms}")
        form.wait_for(state='detached')
        # Every field (including the program's day controls) must survive the
        # extra binding pass while Alpine removes a cancelled form.
        for kind, label in (('thread', 'A conversation with someone outside'),
                            ('mission', 'Work for Argyle'), ('program', 'A practice program')):
            page.locator('[data-add-piece]').click()
            page.locator('[data-prompt-choice]', has_text=label).first.click()
            form = page.locator(f'[data-piece-form="{kind}"]')
            form.wait_for(state='visible')
            if kind == 'program':
                form.get_by_role('button', name='Mon', exact=True).click()
            form.get_by_role('button', name='Cancel', exact=True).click()
            form.wait_for(state='detached')
        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_add_a_piece_for_a_child():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        page.set_viewport_size({'width': 390, 'height': 844})
        pwa(page, served, 'kid')
        page.goto(served.url('app'), wait_until='load')
        page.wait_for_selector('#tab-projects', timeout=15000)
        page.locator('#tab-projects').click()
        page.wait_for_selector('[data-project-id="prj-bike"]', timeout=15000)
        page.locator('[data-project-id="prj-bike"]').click()
        page.wait_for_selector('[data-project-detail]', timeout=10000)
        page.wait_for_selector('[data-add-piece]', timeout=15000)
        page.locator('[data-add-piece]').click()
        choices = page.locator('[data-pick]').all_inner_texts()
        check('Work for Argyle' not in choices and 'A conversation with someone outside' not in choices,
              f"a child adds no Argyle work and no outside conversation: {choices}")
        check(any('practice program' in c for c in choices), f"but may propose their own program: {choices}")


SCENARIOS = [scenario_lanes_and_the_programs_filter, scenario_the_detail_view_and_its_pieces,
             scenario_add_a_piece_inside_the_project, scenario_add_a_piece_for_a_child]

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
