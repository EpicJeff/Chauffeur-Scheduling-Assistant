"""Controller-run browser proof for the final slice-2 review fixes.

Run from chauffeur/: python tests/test_project_final_fixes_live.py
"""
from unittest.mock import patch

from project_sheets_fixture import IDS, admin, check, pwa, serve, shot, storage


def scenario_old_verify_and_missing_mission_sheet():
    served = serve()
    if served is None:
        return
    mid = storage.add_mission({'goal': 'Old booking with verification', 'created_by': 'mom', 'status': 'done', 'created_at': 1})
    attempt = storage.add_mission_step(mid, {'kind': 'attempt', 'result_json': {'outcome': 'unknown'}})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'verify', 'result_json': {'attempt_step_id': attempt}})
    for n in range(61):
        storage.add_mission({'goal': f'Finished job {n}', 'created_by': 'mom', 'status': 'done', 'created_at': 100+n})
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?piece=mission:' + mid), wait_until='load')
        sheet = page.locator('[data-record-sheet]')
        sheet.get_by_role('button', name='It went through', exact=True).first.wait_for(state='visible', timeout=15000)
        sheet.get_by_role('button', name='Delete', exact=True).wait_for(state='visible')
        # The actual poll must keep the old controls, not replace them with the capped list.
        with page.expect_response(lambda r: r.url.endswith('/api/situations/mission/' + mid), timeout=20000):
            pass
        check(sheet.get_by_role('button', name='It went through', exact=True).count() >= 1, 'verification control remains after polling')
        check(sheet.get_by_role('button', name='It went through', exact=True).first.is_visible(), 'verification survives polling')
        shot(page, 'slice2-old-mission-verify')
        page.evaluate("() => window.dispatchEvent(new CustomEvent('chf-record-sheet-open', {detail:{kind:'mission',id:'missing'}}))")
        sheet.get_by_text('That mission isn\u2019t here, or isn\u2019t yours to see.', exact=True).wait_for(state='visible')
        check('Only a parent can launch' not in sheet.inner_text(), 'no misleading parent-only paragraph')


def scenario_finished_keeper_show_closed_and_history():
    served = serve()
    if served is None:
        return
    from services import projects
    mid = storage.add_mission({'goal': 'Finished keeper booking', 'created_by': 'aunt', 'status': 'done', 'created_at': 1})
    projects.adopt('mission', mid, None, project_id='prj-gift')
    with served.browser() as page:
        admin(page, served, 'aunt')
        page.goto(served.url('projects'), wait_until='load')
        page.wait_for_selector('input[x-model="showClosed"]', timeout=15000)
        page.wait_for_selector('[x-data^="projectsPage"] > [x-show="loading"]', state='hidden', timeout=15000)
        piece = page.locator(f'[data-piece-open="mission:{mid}"]')
        check(not piece.is_visible(), 'finished keeper hidden initially')
        page.locator('input[x-model="showClosed"]').check()
        piece.wait_for(state='visible')
        piece.click()
        sheet = page.locator('[data-record-sheet]')
        sheet.get_by_role('button', name='OK', exact=True).wait_for(state='visible', timeout=10000)
        sheet.get_by_role('button', name='Delete', exact=True).wait_for(state='visible')
        shot(page, 'slice2-finished-keeper')


def scenario_restored_creation_choices():
    served = serve()
    if served is None:
        return
    from services import programs_curate
    storage.add_member({'id': 'helper-final', 'name': 'Helper Final', 'role': 'helper'})
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        # One-list + Add (spec 2026-10-20 decision 5): Conversation and Program are its options.
        page.locator('[data-project-add]').click(timeout=15000)
        page.locator('[data-prompt-choice]', has_text='Conversation').first.click()
        form = page.locator('[data-piece-form="thread"]')
        form.locator('input[name="title"]').fill('Unowned final-review loop')
        form.locator('select[name="owner_member_id"]').select_option('')
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/api/threads')) as made:
            form.locator('[data-piece-create]').click()
        check(not storage.get_thread(made.value.json()['id'])['owner_member_id'], 'blank owner stays unowned')
        form.wait_for(state='detached')
        page.locator('[data-project-add]').click()
        page.locator('[data-prompt-choice]', has_text='Program').first.click()
        form = page.locator('[data-piece-form="program"]')
        form.locator('[data-library-make-new]').click()   # since the program library, a new program is Make a new one
        form.locator('input[name="title"]').fill('Helper piano practice')
        form.locator('select[name="for_member_id"]').select_option('helper-final')
        with patch.object(programs_curate, 'curate', return_value={'phases': [], 'source': {}}):
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/api/programs')) as made:
                form.locator('[data-piece-create]').click()
        check(storage.get_program(made.value.json()['id'])['member_id'] == 'helper-final', 'parent can propose for helper')


SCENARIOS = [scenario_old_verify_and_missing_mission_sheet,
             scenario_finished_keeper_show_closed_and_history, scenario_restored_creation_choices]
if __name__ == '__main__':
    import traceback
    failed = 0
    for fn in SCENARIOS:
        try:
            fn()
            print('PASS', fn.__name__)
        except Exception:
            failed += 1
            print('FAIL', fn.__name__)
            traceback.print_exc()
    raise SystemExit(bool(failed))
