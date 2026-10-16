"""A piece opens in the record sheet with everything its old page could do
(front door spec §2, slice 2, Tasks 3 and 4). Run from chauffeur/:
python tests/test_record_sheet_live.py   (PROJECTS_SHOTS=<dir> for screenshots)"""
from project_sheets_fixture import IDS, admin, check, serve, shot


def _sheet(page, key):
    page.locator(f'[data-piece-open="{key}"]').first.click()
    page.wait_for_selector('[data-record-sheet][data-open="true"]', timeout=10000)
    return page.locator('[data-record-sheet]')


def scenario_a_thread_in_the_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-piece-open]', timeout=15000)
        sheet = _sheet(page, f'thread:{IDS["thread"]}')
        page.wait_for_selector('[data-record-sheet] details[open]', timeout=10000)
        text = sheet.inner_text()
        for label in ('Draft email', 'Add note', 'Advance', 'Research', 'Photo', 'Work this', 'Edit', 'Delete', 'Call Ace back', 'Ace Tile'):
            check(label in text, f"the thread sheet has {label}")
        check('Old permit' not in text, "only the thread asked for")
        check('Threads settings' not in page.content() and 'Stalls after' not in text, "no drawer and no page chrome in the sheet")
        check('piece=thread' in page.url, f"the address names the piece: {page.url}")
        shot(page, 'slice2-thread-sheet')
        sheet.get_by_role('button', name='Delete', exact=True).click()
        page.locator('#cc-confirm-modal').wait_for(state='visible', timeout=5000)
        page.keyboard.press('Escape')
        check(page.locator('[data-record-sheet][data-open="true"]').count() == 1,
              "Escape in the delete prompt keeps the thread sheet open")
        page.locator('#cc-confirm-cancel-btn').click()
        page.locator('#cc-confirm-modal').wait_for(state='hidden', timeout=5000)
        page.keyboard.press('Escape')
        page.wait_for_function("() => !document.querySelector('[data-record-sheet]').hasAttribute('data-open')", timeout=5000)
        check('piece=' not in page.url, f"closing drops the piece: {page.url}")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_a_closed_thread_opens_in_the_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath'] + '&piece=thread:' + IDS['closed']), wait_until='load')
        page.wait_for_selector('[data-record-sheet][data-open="true"]', timeout=15000)
        page.wait_for_selector('[data-record-sheet] details[open]', timeout=10000)
        text = page.locator('[data-record-sheet]').inner_text()
        check('Old permit' in text and 'Tiler' not in text, f"a closed thread shows by itself: {text[:300]}")


def scenario_switching_records_shows_only_the_new_one():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath'] + '&piece=thread:' + IDS['closed']), wait_until='load')
        page.wait_for_selector('[data-record-sheet] details[open]', timeout=15000)
        page.evaluate("(id) => window.dispatchEvent(new CustomEvent('chf-record-sheet-open', {detail: {kind: 'thread', id}}))", IDS['thread'])
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').innerText.includes('Call Ace back')", timeout=10000)
        text = page.locator('[data-record-sheet]').inner_text()
        check('Old permit' not in text, f"nothing of the first record lingers: {text[:300]}")


def scenario_a_mission_in_the_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-piece-open]', timeout=15000)
        sheet = _sheet(page, f'mission:{IDS["mission"]}')
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').innerText.includes('Find three tilers')", timeout=15000)
        # Open supplies the header title before loadAdmin finishes. Wait for
        # this mission's answer field inside its open details, not just the title.
        sheet.locator(f'#mission-answer-{IDS["mission"]}').wait_for(state='visible', timeout=15000)
        sheet.get_by_role('button', name='Send', exact=True).wait_for(state='visible', timeout=15000)
        text = sheet.inner_text()
        for label in ('Send', 'Drop', 'Delete'):
            check(label in text, f"the mission sheet has {label}")
        check('Launch a mission' not in text and 'Missions settings' not in page.content(), "no launch card and no drawer in the sheet")
        shot(page, 'slice2-mission-sheet')
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_a_keeper_gets_the_record_alone():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'aunt')
        page.goto(served.url('projects?piece=mission:' + IDS['keeper']), wait_until='load')
        page.wait_for_selector('[data-record-sheet][data-open="true"]', timeout=15000)
        check('Surprise party' not in page.content(), "never the project's words")
        check(page.locator('[data-project-detail]').count() == 0, "no project opened")
        page.goto(served.url('projects'), wait_until='load')
        page.wait_for_selector('[data-lane="elsewhere"]', timeout=15000)
        check('Book the venue' in page.locator('[data-lane="elsewhere"]').inner_text(), "Aunt's work elsewhere lists it")


def scenario_a_program_in_the_sheet():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-piece-open="program:pr-live"]', timeout=15000)
        sheet = _sheet(page, 'program:pr-live')
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').innerText.includes('Strength basics')", timeout=15000)
        # The sheet header has the title before the program's lazy load finishes.
        sheet.get_by_role('button', name='Log a session', exact=True).wait_for(state='visible', timeout=15000)
        text = sheet.inner_text()
        for label in ('Log a session', 'Pause', 'Finished', 'Re-shape the week', 'Drop'):
            check(label in text, f"the active program sheet has {label}")
        check('Tiling basics' not in text and 'Programs settings' not in page.content(), "one program, no drawer")
        page.evaluate("() => window.dispatchEvent(new CustomEvent('chf-record-sheet-open', {detail: {kind: 'program', id: 'pr-prop'}}))")
        page.wait_for_function("() => document.querySelector('[data-record-sheet]').innerText.includes('Tiling basics')", timeout=10000)
        text = page.locator('[data-record-sheet]').inner_text()
        for label in ('Look again', 'Dismiss'):
            check(label in text, f"the proposed program sheet has {label}")
        check('Strength basics' not in text, "only the new one")
        shot(page, 'slice2-program-sheet')
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_the_projects_drawer():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('work?tab=projects#threads-settings'), wait_until='load')
        page.wait_for_selector('[data-settings-for~="projects"][data-open="true"]', timeout=15000)
        drawer = page.locator('[data-settings-for~="projects"]')
        text = drawer.inner_text().lower()
        for label in ('Stalls after', 'Household contact card', 'Pacing'):
            check(label.lower() in text, f"the Projects drawer holds {label}")
        box = drawer.locator('#threadStallDays')
        box.fill('9'); box.dispatch_event('change')
        from project_sheets_fixture import storage
        for _ in range(40):
            if (storage.get_settings() or {}).get('thread_stall_days') == 9:
                break
            page.wait_for_timeout(250)
        check((storage.get_settings() or {}).get('thread_stall_days') == 9, "the moved input still saves")
        shot(page, 'slice2-projects-drawer')
        page.evaluate("(id) => window.dispatchEvent(new CustomEvent('chf-record-sheet-open', {detail: {kind: 'thread', id}}))", IDS['thread'])
        page.wait_for_selector('[data-record-sheet][data-open="true"]', timeout=10000)
        page.keyboard.press('Escape')
        page.wait_for_function("() => !document.querySelector('[data-settings-for=projects]').hasAttribute('data-open')", timeout=5000)
        check(page.locator('[data-record-sheet][data-open="true"]').count() == 1,
              "Escape closes the drawer and keeps the record sheet open")
        page.keyboard.press('Escape')
        page.wait_for_function("() => !document.querySelector('[data-record-sheet]').hasAttribute('data-open')", timeout=5000)
        check(served.errors() == [], f"no page errors: {served.errors()}")


SCENARIOS = [scenario_a_thread_in_the_sheet, scenario_a_closed_thread_opens_in_the_sheet, scenario_switching_records_shows_only_the_new_one,
             scenario_a_mission_in_the_sheet, scenario_a_keeper_gets_the_record_alone, scenario_a_program_in_the_sheet,
             scenario_the_projects_drawer]

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
