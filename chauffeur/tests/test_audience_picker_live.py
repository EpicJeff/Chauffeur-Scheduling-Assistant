"""The shared people picker, served (project audiences spec §5, Task 5).

One picker (components/audience_picker.html) draws who-sees-it on three
surfaces: the Lists page's share popover, the Projects page (create form and
the detail page's audience sheet) and the project chat card's "Choose people…".
The server owns each kind's rules; these cells prove the surfaces post what the
person chose and then show what the server saved.

Run from chauffeur/:  python tests/test_audience_picker_live.py
(PROJECTS_SHOTS=<dir> saves the screenshots.)  No harness.py: enforcement is on.
"""
from project_sheets_fixture import TOKENS, admin, check, pwa, seed, shot, storage

EXTRA = {}


def _seed():
    seed()
    if EXTRA:
        return
    from services import projects, shopping
    from services.agent_tools_v2 import _post_chat_message
    storage.add_member({'id': 'gran', 'name': 'Gran', 'role': 'adult', 'color_code': '#7a5a28',
                        'scope': {'preset': 'keeping_up'}})
    TOKENS['gran'] = storage.create_member_token('gran')
    EXTRA['default'] = storage.ensure_default_shopping_list()['id']
    EXTRA['costco'] = shopping.create_list('Costco', store='Costco')['id']
    EXTRA['hardware'] = shopping.create_list('Hardware', store='Hardware')['id']
    mom, aunt = storage.get_member('mom'), storage.get_member('aunt')
    port = projects.create({'title': 'Learn Portuguese', 'goal': 'Talk with Vó by Christmas', 'done_when': 'a whole call in Portuguese',
                            'audience': 'shared', 'shared_with': ['aunt']}, mom)
    body = projects.create({'title': 'Get down to 185 lbs', 'goal': 'by summer', 'done_when': '185 on the scale'}, mom)
    piano = projects.create({'title': 'Learn piano', 'goal': 'play at the recital', 'done_when': 'the recital'},
                            storage.get_member('kid'))
    check(port['status'] == 'success' and body['status'] == 'success' and piano['status'] == 'success',
          f"seed projects: {port} {body} {piano}")
    EXTRA['port'], EXTRA['body'], EXTRA['piano'] = port['project']['id'], body['project']['id'], piano['project']['id']
    check(storage.get_project(EXTRA['body']).get('body_goal'), "the weight goal is classified as a body goal")
    argyle = storage.ensure_argyle_member()
    for who in ('mom', 'aunt'):
        dm = storage.get_or_create_dm(argyle['id'], who)
        EXTRA['dm_' + who] = dm['id']
        member = storage.get_member(who)
        _post_chat_message(dm, argyle, 'Started a project: Learn Portuguese',
                           card=projects.card(storage.get_project(EXTRA['port']), member, planning='off', reason=''))
    kid_dm = storage.get_or_create_dm(argyle['id'], 'kid')
    EXTRA['dm_kid'] = kid_dm['id']
    _post_chat_message(kid_dm, argyle, 'Started a project: Learn piano',
                       card=projects.card(storage.get_project(EXTRA['piano']), storage.get_member('kid'), planning='needs_parent',
                                          reason='Ask a parent to plan it with Argyle.'))
    _post_chat_message(storage.get_or_create_dm(argyle['id'], 'mom'), argyle, 'Started a project: Get down to 185 lbs',
                       card=projects.card(storage.get_project(EXTRA['body']), mom, planning='off', reason=''))


def serve():
    from live_app import live_app
    served = live_app(_seed)
    if served is not None:
        storage.update_settings({'auth_enforce': True})
    return served


def _get_as(served, who, path):
    """Status of a GET as `who`, through the member token the phone sends."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(served.url(path), headers={'X-Member-Token': TOKENS[who]})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _ticks(scope):
    """{member id: (checked, disabled, hint)} as the picker draws them."""
    return scope.locator('[data-audience-picker]').first.evaluate("""el => Object.fromEntries(
        [...el.querySelectorAll('[data-audience-people] [data-audience-member]')].map(i => [i.dataset.audienceMember,
            [i.checked, i.disabled, ((el.querySelector(`[data-audience-hint="${i.dataset.audienceMember}"]`) || {}).offsetParent
                ? el.querySelector(`[data-audience-hint="${i.dataset.audienceMember}"]`).textContent : '')]]))""")


def _put(served, list_id):
    url = served.url(f'api/shopping/lists/{list_id}')
    return lambda r: r.request.method == 'PUT' and r.url == url


def _open_share(page, name):
    page.locator('button', has_text=name).first.click()
    share = page.locator('button[title="Share this list with someone specific"], button[title="Shared beyond the household defaults"], '
                         'button[title^="Private"]').first
    share.click()
    picker = page.locator('[data-audience-picker]').first
    picker.wait_for(state='visible', timeout=10000)
    return picker


def scenario_the_lists_share_popover():
    served = serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
            page.set_viewport_size({'width': 390, 'height': 844})
            admin(page, served, 'mom')
            page.goto(served.url('lists'), wait_until='load')
            page.wait_for_selector('button:has-text("Costco")', timeout=15000)

            # A household list: the popover lists the members; ticking Gran
            # (keeping up, lists hidden by her scope) keeps the household
            # audience and stores her additive grant.
            picker = _open_share(page, 'Costco')
            names = picker.locator('[data-audience-people] label').all_inner_texts()
            for name in ('Mom', 'Dad', 'Aunt Jo', 'Kate', 'Gran'):
                check(any(name in n for n in names), f"the popover lists {name}: {names}")
            check(picker.locator('[data-audience-value="private"]').count() == 1, "a store list offers the Private switch")
            check('Everyone in the household already sees this list' in picker.inner_text(), "the household note")
            with page.expect_response(_put(served, EXTRA['costco']), timeout=10000) as put:
                picker.locator('[data-audience-member="gran"]').check()
            check(put.value.request.post_data_json.get('shared_with') == ['gran'] and 'audience' not in put.value.request.post_data_json,
                  f"a tick sends only the list, as before: {put.value.request.post_data_json}")
            row = storage.get_shopping_list(EXTRA['costco'])
            check(row.get('audience') in (None, 'household') and row.get('shared_with') == ['gran'],
                  f"the household list keeps its audience and gains Gran's grant: {row}")
            page.wait_for_selector('button[title="Shared beyond the household defaults"]', timeout=5000)
            check(picker.locator('[data-audience-member="gran"]').is_checked(), "Gran stays ticked")
            check(picker.get_attribute('data-audience') == 'household', "still a household list")
            shot(page, 'audience-lists-household')
            page.mouse.click(5, 5)

            # The default list never offers Private (the Lists page shows it
            # when the address pins it).
            page.goto(served.url('lists?list=' + EXTRA['default']), wait_until='load')
            page.wait_for_selector('button:has-text("Groceries")', timeout=15000)
            picker = _open_share(page, 'Groceries')
            check(picker.locator('[data-audience-value="private"]').count() == 0, "the default list hides the Private switch")
            check(picker.locator('[data-audience-people] input').count() >= 5, "but still hands it to people")
            page.mouse.click(5, 5)

            # A list made private: the server adds the person flipping it and
            # the popover shows the server's list, not what was sent.
            page.goto(served.url('lists'), wait_until='load')
            page.wait_for_selector('button:has-text("Hardware")', timeout=15000)
            picker = _open_share(page, 'Hardware')
            with page.expect_response(_put(served, EXTRA['hardware']), timeout=10000) as put:
                picker.locator('[data-audience-value="private"]').check()
            check(put.value.request.post_data_json.get('audience') == 'private' and 'shared_with' not in put.value.request.post_data_json,
                  f"the switch sends only the audience, as before: {put.value.request.post_data_json}")
            row = storage.get_shopping_list(EXTRA['hardware'])
            check(row.get('audience') == 'private' and 'mom' in (row.get('shared_with') or []), f"the server added Mom: {row}")
            page.wait_for_function("() => document.querySelector('[data-audience-member=\"mom\"]:checked') !== null", timeout=5000)
            check(picker.get_attribute('data-audience') == 'private', "the picker reads private")
            check('only the people ticked below' in picker.inner_text(), "the private note")
            shot(page, 'audience-lists-private')
            check(not dialogs, f"no browser dialogs: {dialogs}")
            check(served.errors() == [], f"no page errors: {served.errors()}")
    finally:
        served.stop()


def scenario_projects_page_create_and_detail():
    served = serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
            page.set_viewport_size({'width': 390, 'height': 844})
            admin(page, served, 'mom')
            page.goto(served.url('projects'), wait_until='load')
            page.wait_for_selector('[data-new-project]', timeout=15000)
            page.locator('[data-new-project]').click()
            form = page.locator('form', has=page.locator('[data-create-project]'))
            form.locator('input[name="title"]').fill('Garden shed')
            form.locator('textarea[name="goal"]').fill('a dry place for the bikes')
            picker = form.locator('[data-create-audience] [data-audience-picker]')
            check(picker.get_attribute('data-audience') == 'private', "a parent's new project starts private")
            check(not picker.locator('[data-audience-people]').is_visible() or picker.locator('[data-audience-member="mom"]').is_disabled(),
                  "the owner is fixed on a private list")
            picker.locator('[data-audience-value="shared"]').check()
            picker.locator('[data-audience-member="aunt"]').check()
            ticks = _ticks(form)
            check(ticks['mom'] == [True, True, 'owner'] and ticks['dad'] == [True, True, 'always'],
                  f"in shared mode the owner and every parent are ticked, fixed and say why: {ticks}")
            check(ticks['aunt'] == [True, False, ''] and ticks['kid'] == [False, False, ''] and ticks['gran'] == [False, False, ''],
                  f"only the chosen people are choices: {ticks}")
            shot(page, 'audience-projects-create')
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url == served.url('api/projects'), timeout=10000) as made:
                form.locator('[data-create-project]').click()
            body = made.value.request.post_data_json
            check(body.get('audience') == 'shared' and body.get('shared_with') == ['aunt'],
                  f"the picker's choice is posted, parents and owner left to their role: {body}")
            pid = made.value.json()['project']['id']
            row = storage.get_project(pid)
            check(row['audience'] == 'shared' and row['shared_with'] == ['aunt'], f"saved shared with Aunt: {row}")

            page.goto(served.url('projects?id=' + pid), wait_until='load')
            page.wait_for_selector('[data-audience-row]', timeout=15000)
            label = page.locator('[data-audience-row] [data-audience-label]').inner_text().strip()
            check(label == 'Parents and chosen people', f"the detail Audience row after reload: {label!r}")
            shot(page, 'audience-projects-detail')

            # Change it in the sheet: Private keeps Aunt and the server adds Mom.
            page.locator('[data-audience-change]').click()
            sheet = page.locator('[data-audience-sheet][data-open="true"]')
            sheet.wait_for(state='visible', timeout=5000)
            check(sheet.locator('[data-audience-value="shared"]').is_checked()
                  and sheet.locator('[data-audience-member="aunt"]').is_checked(), "the sheet opens on the saved choice")
            check(_ticks(sheet)['dad'] == [True, True, 'always'], "Dad sees a shared project by role")
            sheet.locator('[data-audience-value="private"]').check()
            ticks = _ticks(sheet)
            check(ticks['mom'] == [True, True, 'owner'] and ticks['aunt'] == [True, False, ''] and ticks['dad'] == [False, False, '']
                  and ticks['kid'][0] is False, f"Private starts from the visible picks; Dad is not carried in: {ticks}")
            shot(page, 'audience-projects-sheet')
            with page.expect_response(lambda r: r.request.method == 'PATCH' and r.url == served.url('api/projects/' + pid), timeout=10000) as patched:
                sheet.locator('[data-audience-save]').click()
            check(patched.value.request.post_data_json == {'audience': 'private', 'shared_with': ['mom', 'aunt']},
                  f"the sheet posts exactly the ticks shown: {patched.value.request.post_data_json}")
            sheet.wait_for(state='hidden', timeout=5000)
            row = storage.get_project(pid)
            check(row['audience'] == 'private' and row['shared_with'] == ['mom', 'aunt'], f"saved as shown: {row}")
            check(_get_as(served, 'dad', 'api/projects/' + pid) == 404 and _get_as(served, 'aunt', 'api/projects/' + pid) == 200,
                  "Dad, unticked, cannot see it; Aunt, ticked, can")
            page.wait_for_function("() => (document.querySelector('[data-audience-label]') || {}).textContent === 'Only Mom, Aunt Jo'", timeout=5000)

            page.goto(served.url('work'), wait_until='load')
            page.wait_for_selector('[data-new-project]', timeout=15000)
            check(page.locator('[data-audience-sheet]').count() == 1, "one audience sheet on the Work host too")

            # The body goal: "Only you", and no picker.
            page.goto(served.url('projects?id=' + EXTRA['body']), wait_until='load')
            page.wait_for_selector('[data-audience-row]', timeout=15000)
            check(page.locator('[data-audience-row] [data-audience-label]').inner_text().strip() == 'Only you', "a body goal reads Only you")
            check(page.locator('[data-audience-change]').count() == 0, "and offers no picker")
            check(not dialogs, f"no browser dialogs: {dialogs}")
            check(served.errors() == [], f"no page errors: {served.errors()}")

            # Aunt is on the list but is neither owner nor parent: no Audience row.
            refused = _watch_refusals(page)
            pwa(page, served, 'aunt')
            page.goto(served.url('app'), wait_until='load')
            page.wait_for_selector('#tab-projects', timeout=15000)
            page.locator('#tab-projects').click()
            page.wait_for_selector(f'[data-project-id="{pid}"]', timeout=15000)
            page.locator(f'[data-project-id="{pid}"]').first.click()
            page.wait_for_selector('[data-project-detail]', timeout=10000)
            check('Garden shed' in page.locator('[data-project-detail]').inner_text(), "Aunt opens the project she is listed on")
            check(page.locator('[data-audience-row]').count() == 0, "a listed adult sees no Audience row")
            shot(page, 'audience-projects-aunt')
            check(_app_errors(served, refused) == [], f"no page errors: {served.errors()} {refused}")
    finally:
        served.stop()


def _app_errors(served, refused):
    """Page errors, less the one an adult's phone always draws: the app reads
    the house settings, which only a parent may (403, logged by the browser)."""
    expected = all(url.endswith('/api/settings') for url in refused)
    return [e for e in served.errors() if not (expected and 'status of 403' in e)]


def _watch_refusals(page):
    refused = []
    page.on('response', lambda r: r.status == 403 and refused.append(r.url))
    return refused


def _open_dm(page, served, who, theme='dark'):
    pwa(page, served, who)
    page.evaluate("(t) => localStorage.setItem('chauffeur_theme', t)", theme)
    page.goto(served.url('app'), wait_until='load')
    page.wait_for_function("() => typeof openChannel === 'function' && typeof membersData !== 'undefined' && membersData.length > 0", timeout=15000)
    if page.locator('#tab-messages').is_visible():
        page.locator('#tab-messages').click()
    page.evaluate("(id) => openChannel(id)", EXTRA['dm_' + who])
    card = page.locator(f'[data-project-card="{EXTRA["piano" if who == "kid" else "port"]}"]').last
    card.wait_for(state='visible', timeout=15000)
    return card


def scenario_the_chat_card():
    served = serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
            page.set_viewport_size({'width': 390, 'height': 844})
            refused = _watch_refusals(page)

            # Aunt's card: listed, may act, may not choose who sees it.
            card = _open_dm(page, served, 'aunt')
            text = card.inner_text()
            check('Rename' in text and 'Choose people' not in text and 'Make private' not in text and 'Share with' not in text,
                  f"Aunt's card offers no audience choices: {text}")
            shot(page, 'audience-card-aunt')

            # Mom's cards: the quick choices plus Choose people…; the body goal
            # card reads Only you and offers none of them.
            card = _open_dm(page, served, 'mom', theme='light')
            text = card.inner_text()
            check('Make private' in text and 'Share with the household' in text and 'Choose people…' in text, f"Mom's card: {text}")
            check('Parents and chosen people' in card.locator('[data-project-audience]').inner_text(), "the chip reads the saved audience")
            body_card = page.locator(f'[data-project-card="{EXTRA["body"]}"]').last
            body_text = body_card.inner_text()
            check('Only you' in body_text and 'Choose people' not in body_text and 'Make private' not in body_text and 'Share with' not in body_text,
                  f"the body goal card: {body_text}")
            shot(page, 'audience-card-body-goal-light')
            card.scroll_into_view_if_needed()
            shot(page, 'audience-card-mom-light')
            card.locator('[data-project-choose-people]').click()
            sheet = page.locator('[data-audience-sheet][data-open="true"]')
            sheet.wait_for(state='visible', timeout=5000)
            check(sheet.locator('[data-audience-member="aunt"]').is_checked(), "the sheet opens on the saved list")
            check(sheet.locator('[data-audience-member="dad"]').is_disabled() and _ticks(sheet)['dad'][2] == 'always',
                  "a parent cannot be unticked from a shared project")
            sheet.locator('[data-audience-member="kid"]').check()
            shot(page, 'audience-card-sheet-light')
            with page.expect_response(lambda r: r.request.method == 'PATCH', timeout=10000) as patched:
                sheet.locator('[data-audience-save]').click()
            check(patched.value.request.post_data_json == {'audience': 'shared', 'shared_with': ['aunt', 'kid']},
                  f"the card's sheet posts the choice, no parent ids: {patched.value.request.post_data_json}")
            sheet.wait_for(state='hidden', timeout=5000)
            row = storage.get_project(EXTRA['port'])
            check(row['audience'] == 'shared' and row['shared_with'] == ['aunt', 'kid'], f"saved: {row}")
            # Private from the sheet: the chip re-reads the server's label.
            card.locator('[data-project-choose-people]').click()
            sheet.wait_for(state='visible', timeout=5000)
            sheet.locator('[data-audience-value="private"]').check()
            with page.expect_response(lambda r: r.request.method == 'PATCH', timeout=10000) as patched:
                sheet.locator('[data-audience-save]').click()
            check(patched.value.request.post_data_json == {'audience': 'private', 'shared_with': ['mom', 'aunt', 'kid']},
                  f"private from shared keeps the visible picks only: {patched.value.request.post_data_json}")
            sheet.wait_for(state='hidden', timeout=5000)
            page.wait_for_function("(id) => [...document.querySelectorAll(`[data-project-card='${id}'] [data-project-audience]`)]"
                                   ".some(el => el.textContent === 'Only Mom, Aunt Jo, Kate')", arg=EXTRA['port'], timeout=5000)
            row = storage.get_project(EXTRA['port'])
            check(row['audience'] == 'private' and row['shared_with'] == ['mom', 'aunt', 'kid'], f"saved private: {row}")
            check(_get_as(served, 'dad', 'api/projects/' + EXTRA['port']) == 404, "Dad, never ticked, cannot see it")
            check(not dialogs, f"no browser dialogs: {dialogs}")
            check(_app_errors(served, refused) == [], f"no page errors: {served.errors()} {refused}")

            card = _open_dm(page, served, 'mom', theme='dark')
            card.locator('[data-project-choose-people]').click()
            page.locator('[data-audience-sheet][data-open="true"]').wait_for(state='visible', timeout=5000)
            shot(page, 'audience-card-sheet-dark')
            page.keyboard.press('Escape')
            page.locator('[data-audience-sheet]').wait_for(state='hidden', timeout=5000)

            # The phone's Projects tab opens the same sheet (app.html hosts it).
            check(page.locator('[data-audience-sheet]').count() == 1, "one audience sheet on the phone")
            page.locator('#tab-projects').click()
            page.wait_for_selector(f'[data-project-id="{EXTRA["port"]}"]', timeout=15000)
            page.locator(f'[data-project-id="{EXTRA["port"]}"]').first.click()
            page.wait_for_selector('[data-audience-row]', timeout=10000)
            check(page.locator('[data-audience-label]').inner_text().strip() == 'Only Mom, Aunt Jo, Kate', "the phone's row reads the saved list")
            page.locator('[data-audience-change]').click()
            sheet = page.locator('[data-audience-sheet][data-open="true"]')
            sheet.wait_for(state='visible', timeout=5000)
            check(sheet.locator('[data-audience-value="private"]').is_checked(), "the phone's sheet opens on the saved choice")
            with page.expect_response(lambda r: r.request.method == 'PATCH', timeout=10000) as patched:
                sheet.locator('[data-audience-value="household"]').check()
                sheet.locator('[data-audience-save]').click()
            check(patched.value.request.post_data_json.get('audience') == 'household', f"{patched.value.request.post_data_json}")
            page.wait_for_function("() => (document.querySelector('[data-audience-label]') || {}).textContent === 'Household'", timeout=5000)
            shot(page, 'audience-projects-phone-dark')
            check(_app_errors(served, refused) == [], f"no page errors: {served.errors()} {refused}")
    finally:
        served.stop()


def scenario_a_childs_private_list_is_what_the_picker_shows():
    """Review fix 1: Private on a child's project pre-ticks the server's default
    list (the child and every parent); what is ticked is what is saved, so a
    parent unticked is a parent who cannot see it."""
    served = serve()
    if served is None:
        return
    try:
        with served.browser() as page:
            dialogs = []
            page.on('dialog', lambda d: (dialogs.append(d.message), d.dismiss()))
            page.set_viewport_size({'width': 390, 'height': 844})
            admin(page, served, 'mom')

            # Changing Kate's parents project to Private, Dad unticked.
            page.goto(served.url('projects?id=prj-bike'), wait_until='load')
            page.wait_for_selector('[data-audience-change]', timeout=15000)
            page.locator('[data-audience-change]').click()
            sheet = page.locator('[data-audience-sheet][data-open="true"]')
            sheet.wait_for(state='visible', timeout=5000)
            sheet.locator('[data-audience-value="private"]').check()
            ticks = _ticks(sheet)
            check(ticks['kid'] == [True, True, 'owner'] and ticks['mom'][:2] == [True, False] and ticks['dad'][:2] == [True, False]
                  and ticks['aunt'][0] is False, f"a child's Private pre-ticks the default list: {ticks}")
            sheet.locator('[data-audience-member="dad"]').uncheck()
            shot(page, 'audience-child-private-sheet')
            with page.expect_response(lambda r: r.request.method == 'PATCH', timeout=10000) as patched:
                sheet.locator('[data-audience-save]').click()
            check(patched.value.request.post_data_json == {'audience': 'private', 'shared_with': ['kid', 'mom']},
                  f"the list shown is the list sent: {patched.value.request.post_data_json}")
            sheet.wait_for(state='hidden', timeout=5000)
            row = storage.get_project('prj-bike')
            check(row['audience'] == 'private' and row['shared_with'] == ['kid', 'mom'], f"saved as ticked: {row}")
            check(_get_as(served, 'dad', 'api/projects/prj-bike') == 404, "Dad, unticked, cannot see Kate's project")
            check(_get_as(served, 'mom', 'api/projects/prj-bike') == 200 and _get_as(served, 'kid', 'api/projects/prj-bike') == 200,
                  "Mom and Kate still can")
            page.wait_for_function("() => (document.querySelector('[data-audience-label]') || {}).textContent === 'Only Kate, Mom'",
                                   timeout=5000)

            # Creating one for Kate: the same default list, Dad unticked.
            page.goto(served.url('projects'), wait_until='load')
            page.wait_for_selector('[data-new-project]', timeout=15000)
            page.locator('[data-new-project]').click()
            form = page.locator('form', has=page.locator('[data-create-project]'))
            form.locator('input[name="title"]').fill('Science fair')
            form.locator('select[name="owner_member_id"]').select_option('kid')
            picker = form.locator('[data-create-audience] [data-audience-picker]')
            check(picker.get_attribute('data-audience') == 'parents', "a child's new project starts with the parents")
            picker.locator('[data-audience-value="private"]').check()
            ticks = _ticks(form)
            check(ticks['kid'] == [True, True, 'owner'] and ticks['mom'][0] and ticks['dad'][0], f"the default list is shown: {ticks}")
            picker.locator('[data-audience-member="dad"]').uncheck()
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url == served.url('api/projects'), timeout=10000) as made:
                form.locator('[data-create-project]').click()
            body = made.value.request.post_data_json
            check(body.get('audience') == 'private' and body.get('shared_with') == ['kid', 'mom'], f"created as shown: {body}")
            pid = made.value.json()['project']['id']
            check(storage.get_project(pid)['shared_with'] == ['kid', 'mom'], f"saved: {storage.get_project(pid)}")
            check(_get_as(served, 'dad', 'api/projects/' + pid) == 404, "Dad cannot see the new one either")
            check(not dialogs, f"no browser dialogs: {dialogs}")
            check(served.errors() == [], f"no page errors: {served.errors()}")

            # Kate's own chat card offers all four values, Household included.
            refused = _watch_refusals(page)
            card = _open_dm(page, served, 'kid')
            check('Choose people…' in card.inner_text(), f"Kate's card offers Choose people…: {card.inner_text()}")
            card.locator('[data-project-choose-people]').click()
            sheet.wait_for(state='visible', timeout=5000)
            values = sheet.locator('[data-audience-value]').evaluate_all("els => els.map(e => e.value)")
            check(values == ['household', 'parents', 'shared', 'private'], f"a child gets all four values: {values}")
            check(sheet.locator('[data-audience-value="parents"]').is_checked(), "on the saved choice")
            shot(page, 'audience-card-child-sheet')
            check(_app_errors(served, refused) == [], f"no page errors: {served.errors()} {refused}")
    finally:
        served.stop()


SCENARIOS = [scenario_the_lists_share_popover, scenario_projects_page_create_and_detail, scenario_the_chat_card,
             scenario_a_childs_private_list_is_what_the_picker_shows]

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
