"""The Projects page as one list (one-list spec §3-§4, Task 4): a project's
detail is Now / Next / Later / Linked / Logbook rows with a checkbox each, one
⋯ and one + Add, a step sheet and a link sheet; the list page groups Needs you
then everything else, with no state chip and no Programs filter. Run from
chauffeur/: python tests/test_projects_detail_live.py   (PROJECTS_SHOTS=<dir> for screenshots)"""
from project_sheets_fixture import IDS, admin, check, open_projects, pwa, serve, shot, storage


def scenario_detail_is_one_list():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-bath'), wait_until='load')
        page.wait_for_selector('[data-project-detail]', timeout=15000)
        page.wait_for_selector('[data-row]', timeout=15000)
        buttons = page.locator('[data-project-detail] button:visible')
        rows = page.locator('[data-row]:visible')
        n_rows, n_buttons = rows.count(), buttons.count()
        asking = page.locator('[data-row-box][data-box-state="asking"]:visible').count()
        toggle = page.locator('[data-row-group-section="logbook"] > button:visible').count()
        # box + title per visible row, the ⋯, + Add, the back link and the Logbook toggle, plus asking rows' own buttons
        check(n_buttons <= 2 * n_rows + 3 + toggle + 3 * asking,
              f"{n_buttons} buttons for {n_rows} visible rows ({asking} asking, {toggle} Logbook toggle)")
        check(page.locator('[data-project-menu]').count() == 1 and page.locator('[data-project-add]').count() == 1, "one ⋯ and one + Add")
        check(page.locator('[data-new-project]').count() == 0, "no New project accordion on the detail")
        groups = [g for g in ('now', 'next', 'later', 'linked', 'logbook') if page.locator(f'[data-row-group="{g}"]').count()]
        check('now' in groups, f"the fixture's waiting mission makes a Now group: {groups}")
        texts = ' '.join(page.locator('[data-row]').all_inner_texts())
        check('waiting_user' not in texts and 'active' not in texts.split(), f"no state codes on rows: {texts[:200]}")
        shot(page, 'one-list-detail')
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_menu_and_add():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-bath'), wait_until='load')
        page.wait_for_selector('[data-project-menu]', timeout=15000)
        page.locator('[data-project-menu]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        labels = page.locator('#cc-choice-modal button').all_inner_texts()
        for want in ('Plan it with Argyle', 'Who sees it', 'Pause', 'Mark done', 'Drop', 'Delete'):
            check(any(want in l for l in labels), f"⋯ holds {want}: {labels}")
        page.keyboard.press('Escape')
        page.locator('[data-project-add]').click()
        page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
        labels = page.locator('#cc-choice-modal button').all_inner_texts()
        for want in ('Step', 'Conversation', 'Ask Argyle', 'Program', 'Something already in Chauffeur'):
            check(any(want in l for l in labels), f"+ Add offers {want}: {labels}")
        page.keyboard.press('Escape')
        shot(page, 'one-list-add')


def scenario_tick_a_step_and_open_sheets():
    served = serve()
    if served is None:
        return
    from services import projects
    step = projects.add_step('prj-bath', {'title': 'Demo the old tile', 'owner': 'mom'}, storage.get_member('mom'))['step']
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-bath'), wait_until='load')
        row = page.locator(f'[data-row="step:{step["id"]}"]')
        row.wait_for(timeout=15000)
        row.locator('[data-row-box]').click()
        page.wait_for_selector(f'[data-row="step:{step["id"]}"][data-row-group="logbook"]', timeout=10000)
        check(storage.get_project('prj-bath')['steps'][-1]['state'] == 'done', "the tick landed")
        row.locator('[data-row-title]').click()
        page.wait_for_selector('[data-step-sheet]', timeout=5000)
        check(page.locator('[data-step-sheet]').inner_text().count('Put it on the calendar') == 1, "the step sheet holds the calendar control")
        page.keyboard.press('Escape')
        thread = page.locator(f'[data-row="conversation:{IDS["thread"]}"]')
        thread.locator('[data-row-title]').click()
        page.wait_for_selector('[data-record-sheet][data-open="true"][data-kind="thread"]', timeout=5000)
        # The sheet opens on its title and draws the card a moment later (a pre-existing race: 1 in 6 at 97081e29).
        page.wait_for_selector('[data-record-sheet][data-open="true"] .situation-card', timeout=5000)
        check('Draft a message' in page.locator('[data-record-sheet]').inner_text(), "the thread sheet keeps its verbs")
        shot(page, 'one-list-sheets')


def scenario_conversation_ticks_and_unticks():
    """A conversation's box finishes its next step; left with no successor the
    row reads done in the Logbook, and one more tap restores the step (spec §2.2)."""
    served = serve()
    if served is None:
        return
    tid = IDS['thread']
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-bath'), wait_until='load')
        row = page.locator(f'[data-row="conversation:{tid}"]')
        row.wait_for(timeout=15000)
        check(row.locator('[data-row-box]').get_attribute('data-box-state') == 'open', "the next step is open")
        # Answered: the successor is set through /advance and becomes the row.
        successor = 'Send Ace the floor plan'
        row.locator('[data-row-box]').click()
        page.locator('#cc-input-modal:not(.hidden)').wait_for(timeout=10000)
        check("What's next with Ace Tile?" in page.locator('#cc-input-title').inner_text(), "it asks for the successor")
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith(f'api/threads/{tid}/advance'), timeout=10000) as adv:
            page.locator('#cc-input-field').fill(successor)
            page.locator('#cc-input-ok-btn').click()
        check(adv.value.status == 200, f"the successor was saved: {adv.value.status} {adv.value.text()}")
        page.wait_for_function("""({sel, text}) => { const t = document.querySelector(sel + ' [data-row-title]');
            const b = document.querySelector(sel + ' [data-row-box]');
            return t && b && t.innerText.trim() === text && b.dataset.boxState === 'open'; }""",
                               arg={'sel': f'[data-row="conversation:{tid}"]', 'text': successor}, timeout=10000)
        check(storage.get_thread(tid).get('next_action') == successor, f"the thread carries the successor: {storage.get_thread(tid)}")
        # Left empty: the finished step reads done in the Logbook until it is unticked.
        row.locator('[data-row-box]').click()
        page.locator('#cc-input-modal:not(.hidden)').wait_for(timeout=10000)
        page.locator('#cc-input-cancel-btn').click()
        page.wait_for_selector(f'[data-row="conversation:{tid}"][data-row-group="logbook"] [data-row-box][data-box-state="done"]:not([disabled])',
                               timeout=10000)
        check(not storage.get_thread(tid).get('next_action'), "the next step was finished")
        check(successor in row.inner_text(), f"the done row keeps the step's words: {row.inner_text()}")
        shot(page, 'one-list-conversation-done')
        row.locator('[data-row-box]').click()
        page.wait_for_selector(f'[data-row="conversation:{tid}"] [data-row-box][data-box-state="open"]', timeout=10000)
        check(storage.get_thread(tid).get('next_action') == successor, f"the untick restored it: {storage.get_thread(tid)}")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_asking_row_posts_through_the_situation():
    """An asking row's button posts the situation card's own act (spec §1.3),
    never only opening the sheet. The act is intercepted: the fixture stays asking."""
    served = serve()
    if served is None:
        return
    mid = IDS['mission']
    with served.browser() as page:
        admin(page, served, 'mom')
        posted = []

        def fake(route):
            posted.append(route.request.post_data_json)
            route.fulfill(status=200, content_type='application/json', body='{"status": "success"}')

        page.route(f'**/api/situations/mission/{mid}/act', fake)
        page.goto(served.url('projects?id=prj-bath'), wait_until='load')
        row = page.locator(f'[data-row="argyle:{mid}"]')
        row.wait_for(timeout=15000)
        check(row.locator('[data-row-box]').get_attribute('data-box-state') == 'asking', "the mission asks")
        row.locator('[data-row-action]', has_text='Answer').click()
        page.locator('#cc-input-modal:not(.hidden)').wait_for(timeout=10000)
        page.locator('#cc-input-field').fill('Thursday')
        page.locator('#cc-input-ok-btn').click()
        for _ in range(40):
            if posted:
                break
            page.wait_for_timeout(250)
        check(posted and posted[0].get('verb') == 'answer' and posted[0].get('payload', {}).get('text') == 'Thursday',
              f"Answer posted the situation act with the typed answer: {posted}")
        check(page.locator('[data-record-sheet][data-open="true"]').count() == 0, "no sheet opened instead")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_add_a_step_to_a_paused_project():
    served = serve()
    if served is None:
        return
    pid = 'prj-bike'
    original = storage.get_project(pid)['state']
    storage.update_project(pid, {'state': 'paused'})
    try:
        with served.browser() as page:
            admin(page, served, 'mom')
            page.goto(served.url('projects?id=' + pid), wait_until='load')
            page.wait_for_selector('[data-project-add]', timeout=15000)
            page.locator('[data-project-add]').click()
            page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
            labels = [l.strip() for l in page.locator('#cc-choice-modal [data-prompt-choice]').all_inner_texts()]
            check(labels == ['Step'], f"a paused project takes steps only: {labels}")
            page.locator('[data-prompt-choice]', has_text='Step').first.click()
            page.locator('#cc-input-modal:not(.hidden)').wait_for(timeout=5000)
            page.locator('#cc-input-field').fill('Oil the chain')
            page.locator('#cc-input-ok-btn').click()
            page.wait_for_selector('#cc-choice-modal:not(.hidden)', timeout=5000)
            page.locator('[data-prompt-choice]', has_text='Kate').first.click()
            for _ in range(40):
                if any(s.get('title') == 'Oil the chain' for s in storage.get_project(pid)['steps']):
                    break
                page.wait_for_timeout(250)
            check(any(s.get('title') == 'Oil the chain' and s.get('owner') == 'kid' for s in storage.get_project(pid)['steps']),
                  f"the step joined the paused project: {storage.get_project(pid)['steps']}")
            page.wait_for_selector('[data-row^="step:"]', timeout=10000)
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        steps = [x for x in storage.get_project(pid)['steps'] if x.get('title') != 'Oil the chain']
        storage.update_project(pid, {'state': original, 'steps': steps})


def scenario_list_page_groups():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects'), wait_until='load')
        page.wait_for_selector('[data-project-card]', timeout=15000)
        check(page.locator('[data-lane-filter="programs"]').count() == 0, "the Programs filter is gone (R5)")
        check(page.locator('[data-list-group="needs_you"]').count() == 1, "Needs you first")
        check(page.locator('[data-list-group="rest"]').count() <= 1, "then everything else")
        import re
        for card in page.locator('[data-project-card]').all():
            pid = card.locator('[data-project-id]').get_attribute('data-project-id')
            lines = [l for l in card.inner_text().splitlines() if l.strip() and not re.fullmatch(r'\d+ of \d+ done', l.strip())]
            words = set(re.findall(r'[a-z_]+', ' '.join(lines)))
            banned = {'active', 'paused', 'waiting_user', 'done', 'dropped'}
            if storage.get_project(pid).get('state') == 'paused':
                banned.discard('paused')   # a paused card says so in words (spec §4)
            check(not (words & banned), f"no state words on the {pid} card: {lines}")
        page.locator('[data-new-project]').click()
        page.wait_for_selector('[data-create-project]', timeout=5000)
        shot(page, 'one-list-list')


def scenario_closed_projects_are_hidden_folded_and_remembered():
    served = serve()
    if served is None:
        return
    from services import projects
    project_id = 'prj-bike'  # No work or pieces to stop; restore for later scenarios.
    original_state = storage.get_project(project_id)['state']
    try:
        result = projects.set_state(project_id, 'done', storage.get_member('mom'))
        check(result.get('status') == 'success', f"the fixture project is done: {result}")
        with served.browser() as page:
            admin(page, served, 'mom')
            with page.expect_response(lambda r: r.request.method == 'GET' and
                                      r.url == served.url('api/projects'), timeout=15000) as loaded:
                page.goto(served.url('projects'), wait_until='load')
            response = loaded.value
            check(response.status == 200, f"the overview loads: {response.status} {response.text()}")
            closed = next((p for p in response.json()['projects'] if p['id'] == project_id), None)
            check(closed and closed['state'] == 'done' and closed['lane'] == 'closed',
                  f"the loaded overview includes the closed fixture project: {closed}")
            page.wait_for_selector(f'[data-project-id="{IDS["bath"]}"]', timeout=15000)
            toggle = page.get_by_role('checkbox', name='Show closed', exact=True)
            toggle.wait_for(state='visible', timeout=10000)
            lane = page.locator('[data-list-group="closed"]')
            card = page.locator(f'[data-project-id="{project_id}"]')
            check(not toggle.is_checked(), "Show closed starts unchecked")
            check(card.count() == 0 and lane.count() == 0,
                  "the loaded closed project and its lane are absent by default")

            toggle.check()
            lane.wait_for(state='visible', timeout=10000)
            card.wait_for(state='attached', timeout=10000)
            header = lane.locator('button').first
            check('Done & dropped' in header.text_content(), "the closed lane names its contents")
            check(header.get_by_text('Show', exact=True).is_visible() and not card.is_visible(),
                  "Show closed reveals a folded lane with its project hidden")
            header.click()
            card.wait_for(state='visible', timeout=10000)
            check('Ride a bike' in card.inner_text() and header.get_by_text('Hide', exact=True).is_visible(),
                  "unfolding the closed lane reveals the closed project's card")
            check(page.evaluate("() => localStorage.getItem('chf_projects_show_closed')") == '1',
                  "Show closed stores the choice")

            page.reload(wait_until='load')
            lane.wait_for(state='visible', timeout=15000)
            card.wait_for(state='attached', timeout=10000)
            check(toggle.is_checked() and
                  page.evaluate("() => localStorage.getItem('chf_projects_show_closed')") == '1',
                  "Show closed stays checked across reload")
            check(header.get_by_text('Show', exact=True).is_visible() and not card.is_visible(),
                  "the remembered closed lane starts folded again after reload")
            header.click()
            card.wait_for(state='visible', timeout=10000)
            check('Ride a bike' in card.inner_text(), "the remembered lane still unfolds to its project")
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        storage.update_project(project_id, {'state': original_state})
        served.stop()


def scenario_add_through_the_one_add():
    """+ Add opens today's thread, mission and program forms inside the project."""
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=' + IDS['bath']), wait_until='load')
        page.wait_for_selector('[data-project-add]', timeout=15000)
        page.locator('[data-project-add]').click()
        page.locator('[data-prompt-choice]', has_text='Conversation').first.click()
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
        page.wait_for_selector(f'[data-row="conversation:{rows[0]["id"]}"]', state='attached', timeout=10000)
        page.locator('[data-project-add]').click()
        page.locator('[data-prompt-choice]', has_text='Ask Argyle').first.click()
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
        # Every field must survive the extra binding pass while Alpine removes a
        # cancelled form; Program is the one-pass setup sheet (programs spec §4).
        for kind, label in (('thread', 'Conversation'), ('mission', 'Ask Argyle')):
            page.locator('[data-project-add]').click()
            page.locator('[data-prompt-choice]', has_text=label).first.click()
            form = page.locator(f'[data-piece-form="{kind}"]')
            form.wait_for(state='visible')
            form.get_by_role('button', name='Cancel', exact=True).click()
            form.wait_for(state='detached')
        page.locator('[data-project-add]').click()
        page.locator('[data-prompt-choice]', has_text='Program').first.click()
        sheet = page.locator('[data-setup-sheet]')
        sheet.wait_for(state='visible')
        check(page.locator('[data-piece-form="program"]').count() == 0, "no inline program form any more")
        sheet.locator('[data-setup-pick]').first.click()
        sheet.locator('[data-setup-slot]').first.wait_for(state='visible', timeout=10000)
        sheet.locator('[data-setup-close]').click()
        sheet.wait_for(state='detached')
        page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
        check(served.errors() == [], f"no page errors: {served.errors()}")


def scenario_add_for_a_child():
    served = serve()
    if served is None:
        return
    with served.browser() as page:
        page.on('dialog', lambda d: d.dismiss())
        page.set_viewport_size({'width': 390, 'height': 844})
        pwa(page, served, 'kid')
        page.goto(served.url('app'), wait_until='load')
        page.wait_for_selector('#tab-more', state='visible', timeout=15000)
        open_projects(page)
        page.wait_for_selector('[data-project-id="prj-bike"]', timeout=15000)
        page.locator('[data-project-id="prj-bike"]').click()
        page.wait_for_selector('[data-project-detail]', timeout=10000)
        page.wait_for_selector('[data-project-add]', timeout=15000)
        page.locator('[data-project-add]').click()
        page.wait_for_selector('[data-pick]', timeout=5000)
        choices = page.locator('[data-pick]').all_inner_texts()
        check(not any('Ask Argyle' in c or 'Conversation' in c for c in choices),
              f"a child adds no Argyle work and no outside conversation: {choices}")
        check(any('Step' in c for c in choices) and any('Program' in c for c in choices),
              f"but may add a step or propose their own program: {choices}")
        shot(page, 'one-list-phone-kid')


def scenario_program_choice_row_buttons_send_their_option():
    """Use / Make new / Not now on an asking row post the option's own payload
    to the real act endpoint (final review, Codex 4): no typed answer is asked
    for, and the server's payload.option guard passes. Only the planner's
    answer_program_choice is stubbed, so the fixture stays waiting."""
    served = serve()
    if served is None:
        return
    from unittest.mock import patch
    from services import projects, planned
    storage.add_project({'id': 'prj-piano', 'title': 'Piano', 'goal': 'play a song', 'done_when': 'a song',
                         'owner_member_id': 'mom', 'created_by': 'mom', 'audience': 'household', 'pieces': [], 'steps': []})
    mid = storage.add_mission({'goal': 'Find a piano course', 'created_by': 'mom', 'tier': 'mission', 'status': 'waiting_user',
                               'program_choices': [{'id': 'pc1', 'state': 'waiting_choice', 'result': {
                                   'choice_id': 'cid1', 'choice': {'created_by': 'mom', 'member_id': 'mom', 'profile': {}}}}]})
    storage.add_mission_step(mid, {'kind': 'ask', 'name': 'program_choice',
                                   'result_json': {'choice_id': 'cid1', 'question': 'Use the piano course in the library?'}})
    projects.adopt('mission', mid, None, project_id='prj-piano')
    calls = []

    def answered(sid, choice_id, option, actor):
        calls.append((sid, choice_id, option, (actor or {}).get('id')))
        return {'status': 'success', 'already': True}

    with patch.object(planned, 'answer_program_choice', answered), served.browser() as page:
        admin(page, served, 'mom')
        page.goto(served.url('projects?id=prj-piano'), wait_until='load')
        row = page.locator(f'[data-row="argyle:{mid}"]')
        row.wait_for(timeout=15000)
        check(row.locator('[data-row-box]').get_attribute('data-box-state') == 'asking', "the program choice asks")
        for label, option in (('Use', 'use'), ('Make new', 'make_new'), ('Not now', 'not_now')):
            sel = f'[data-row="argyle:{mid}"] [data-row-action="answer:program_choice:cid1:{option}"]'
            page.wait_for_function("sel => { const b = document.querySelector(sel); return b && !b.disabled; }", arg=sel, timeout=10000)
            button = page.locator(sel)
            check(button.inner_text().strip() == label, f"the row offers {label}: {button.inner_text()}")
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith(f'api/situations/mission/{mid}/act'),
                                      timeout=10000) as act:
                button.click()
            body = act.value.request.post_data_json
            check(act.value.status == 200 and body['option_id'] == f'answer:program_choice:cid1:{option}'
                  and body['payload'].get('option') == option and body['payload'].get('choice_id') == 'cid1'
                  and 'text' not in body['payload'], f"{label} posts its own option: {act.value.status} {body} {act.value.text()}")
            check(page.locator('#cc-input-modal:not(.hidden)').count() == 0, f"{label} asks for no typed answer")
            check(calls and calls[-1] == (mid, 'cid1', option, 'mom'), f"the server answered {option}: {calls}")
        check(len(calls) == 3, f"three choices, three answers: {calls}")
        check(served.errors() == [], f"no page errors: {served.errors()}")


SCENARIOS = [scenario_detail_is_one_list, scenario_menu_and_add, scenario_tick_a_step_and_open_sheets,
             scenario_conversation_ticks_and_unticks, scenario_asking_row_posts_through_the_situation,
             scenario_add_a_step_to_a_paused_project,
             scenario_list_page_groups, scenario_closed_projects_are_hidden_folded_and_remembered,
             scenario_add_through_the_one_add, scenario_add_for_a_child,
             scenario_program_choice_row_buttons_send_their_option]


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
