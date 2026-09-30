"""Populated, interactive child acceptance checks for the served PWA harness."""
from pathlib import Path
from pwa_profile_checks import check_profile_button
from urllib.parse import parse_qs, urlparse


def install_child_data(page, key, day):
    items = [dict(id='breakfast', title='Breakfast and teeth', time_of_day='07:00', checked=True, emoji='🪥'),
             dict(id='bag', title='Pack your bag', description='Everything you need for practice.', time_of_day='12:00', checked=False, emoji='🎒',
                  steps=[dict(id='water', title='Water bottle', emoji='💧'), dict(id='shoes', title='Indoor shoes', emoji='👟')], steps_checked=[]),
             dict(id='book', title='Read for ten minutes', time_of_day='18:00', checked=False, emoji='📖')]
    calls = []
    def own_day(route):
        calls.append(route.request.url)
        date = parse_qs(urlparse(route.request.url).query)['date'][0]
        ride = dict(id='practice', title='Soccer practice', start=date+'T16:00:00', end=date+'T17:00:00', location='Riverside fields',
                    driver=dict(name='Alex', member_id='parent', color_code='#287a72'), prep=['Indoor shoes','Water bottle'],
                    legs=[dict(type='dropoff', start=date+'T15:15:00', driver=dict(name='Alex', member_id='parent', color_code='#287a72'))])
        route.fulfill(json=dict(rides=[ride], due_soon=[], status_days=[]))
    page.route('**/api/members/*/day?*', own_day)
    page.route('**/api/routines/day?*', lambda r:r.fulfill(json=dict(items=items,streak={})))
    def check(route):
        body = route.request.post_data_json
        assert body['member_id'] == key
        ident = route.request.url.split('/routines/')[1].split('/')[0]
        item = next(i for i in items if i['id'] == ident)
        if '/steps/' in route.request.url:
            done = set(item['steps_checked'])
            (done.add if body['checked'] else done.discard)(body['step_id'])
            item['steps_checked'] = list(done)
            item['checked'] = len(done) == len(item['steps'])
        else:
            item['checked'] = body['checked']
        calls.append(body)
        route.fulfill(json={'item_checked':item['checked']})
    page.route('**/api/routines/*/check', check)
    page.route('**/api/routines/*/steps/check', check)
    page.route('**/api/points', lambda r:r.fulfill(json=[dict(member_id=key,balance=45)]))
    page.route('**/api/rewards', lambda r:r.fulfill(json=[dict(id='movie', title='Choose movie night', cost=30)]))
    return calls


def check_child(page, key, output, calls):
    def shot(name):
        page.wait_for_timeout(350)
        if output: Path(output, key+'-'+name+'.png').write_bytes(page.screenshot())
    page.wait_for_selector('.child-greeting')
    assert page.locator('html').get_attribute('data-child-stage') == key
    tabs = [' '.join(x.split()) for x in page.locator('#pwa-tab-bar > button:visible > span:first-of-type').all_text_contents()]
    expected = ['Today','My things','Family'] if key == 'sprout' else ['Today','Tasks','Messages','More'] if key == 'explorer' else ['Today','Plan','Tasks','Messages','More']
    assert tabs == expected, (key,tabs)
    assert page.locator('#btn-pet').is_hidden()
    assert page.locator('.child-pickup').inner_text().find('Alex') >= 0
    assert page.locator('.child-pickup').evaluate('(e)=>e.getBoundingClientRect().top') < page.locator('.child-step, .child-priorities').evaluate('(e)=>e.getBoundingClientRect().top')
    shot('today-light')
    if key in ('navigator', 'copilot'):
        check_child_day_navigation(page, key, calls, output)
    else:
        assert page.locator('.child-day-nav').count() == 0
    page.locator('.child-pickup-compact' if key in ('sprout','explorer') else '.child-pickup button').first.click()
    assert 'Indoor shoes' in page.locator('#pwa-child-detail-body').inner_text()
    assert 'Alex' in page.locator('#pwa-child-detail-body').inner_text()
    assert page.locator('#pwa-child-detail').evaluate('(e)=>e.scrollWidth <= e.clientWidth')
    shot('ride-sheet-light')
    page.get_by_role('button',name='Close details',exact=True).click()
    if key == 'sprout': page.locator('.child-step .child-primary').click()
    else: page.locator('.child-priorities .child-task-details').first.click()
    page.locator('#pwa-child-detail-body input[type=checkbox]').first.check()
    page.wait_for_function("pwaChildDay.items.find(i=>i.id==='bag').steps_checked.includes('water')")
    shot('routine-sheet-light')
    page.get_by_role('button',name='Close details',exact=True).click()
    if key == 'sprout': page.locator('.child-step .child-primary').click()
    else: page.locator('.child-priorities .child-task-details').first.click()
    assert page.locator('#pwa-child-detail-body input[type=checkbox]').first.is_checked()
    page.locator('#pwa-child-detail-body input[type=checkbox]').nth(1).check()
    page.wait_for_function("pwaChildDay.items.find(i=>i.id==='bag').checked")
    page.get_by_role('button',name='Close details',exact=True).click()
    assert sum(isinstance(c,dict) for c in calls) == 2
    if key == 'sprout': assert 'Read for ten minutes' in page.locator('.child-step').inner_text()
    else: assert 'Pack your bag' not in page.locator('.child-priorities').inner_text()
    if key != 'sprout':
        page.get_by_role('button',name='See my week →' if key == 'explorer' else 'My plan →',exact=True).click()
        page.wait_for_selector('.child-dates')
        assert page.locator('.child-dates button').count() == (7 if key == 'explorer' else 14)
        page.locator('.child-dates button').nth(1).click()
        page.wait_for_function('pwaChildDay.offset === 1')
        assert page.locator('.child-priorities input:enabled').count() == 0
        assert all('/members/'+key+'/day?' in c for c in calls if isinstance(c,str))
        shot('plan-light')
        page.locator('#tab-myday').click()
        page.wait_for_function('pwaChildDay.offset === 0 && !pwaChildPlan')
    page.evaluate("setView('chores')")
    page.wait_for_selector('[data-child-house="tasks"]')
    assert page.locator('[data-child-house="rewards"]').is_hidden()
    shot('tasks-light')
    page.get_by_role('button',name='Rewards',exact=True).click()
    assert page.get_by_text('Choose movie night',exact=True).is_visible()
    shot('rewards-light')
    page.locator('#tab-messages').click()
    assert page.evaluate('document.activeElement.id') == 'tab-messages'
    page.wait_for_selector('#channel-list > button')
    shot('messages-light')
    page.locator('#tab-more').click()
    page.wait_for_selector('#pwa-feature-list > button')
    assert page.locator('[data-feature="map"]').is_visible()
    assert page.locator('[data-feature="music"]').is_visible()
    assert page.locator('[data-feature="critter"]').first.is_visible()
    shot('more-light')
    page.locator('#pwa-identity').click()
    shot('profile-sheet-light')
    page.get_by_role('button',name='Close profile',exact=True).click()
    page.locator('#tab-myday').click()
    page.wait_for_selector('.child-greeting')
    page.evaluate("applyTheme('dark')")
    shot('today-dark')
    page.evaluate("void promptConfirm('Keep this change?', 'Your family will see the update.').then(()=>{})")
    assert page.locator('.pwa-prompt-overlay .pwa-sheet-head').is_visible()
    shot('confirm-sheet-dark')
    page.locator('.pwa-prompt-overlay [data-no]').click()
    page.evaluate("applyTheme('light')")
    for width in (320,768):
        page.set_viewport_size(dict(width=width,height=844))
        page.evaluate("document.documentElement.style.fontSize='200%'")
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (key,width)
        assert page.locator('#myday-content').evaluate('(e)=>e.scrollWidth <= e.clientWidth'), (key,width)
        shot(str(width)+'-large-text')
    page.evaluate("document.documentElement.style.fontSize=''")
    page.set_viewport_size(dict(width=390,height=844))
    # A parent can override capabilities independently of the visual stage.
    if key == 'navigator':
        page.evaluate("""()=>{
            const me = membersData.find(m=>m.id===selectedMemberId);
            window.savedChildCaps = structuredClone(me.capabilities);
            window.savedChildScope = structuredClone(me.scope_map);
            me.capabilities.can_request=false; me.capabilities.horizon_days=1;
            me.scope_map={facets:{'presence.location':'none',music:'none','chores.board':'none'}};
            applyRoleTabs(); pwaChildOpenPlan();
        }""")
        page.wait_for_selector('.child-dates')
        assert page.locator('.child-dates button').count() == 2
        page.locator('.child-day-nav [data-day-action="next"]').click()
        page.wait_for_function('pwaChildDay.offset === 1')
        assert page.locator('.child-day-nav [data-day-action="next"]').is_disabled()
        page.get_by_role('button', name='Back to today', exact=True).click()
        page.wait_for_function('pwaChildDay.offset === 0')
        assert page.get_by_role('button',name='Ask for a change',exact=True).count() == 0
        page.locator('#tab-more').click()
        assert page.locator('#pwa-feature-list [data-feature="map"]').count() == 0
        assert page.locator('#pwa-feature-list [data-feature="music"]').count() == 0
        page.evaluate("""()=>{
            const me=membersData.find(m=>m.id===selectedMemberId);
            me.capabilities=savedChildCaps; me.scope_map=savedChildScope;
            applyRoleTabs(); setView('myday');
        }""")
        page.wait_for_selector('.child-greeting')
    # Direct completion (not only substeps) refreshes the visible next action.
    if key == 'sprout': page.locator('.child-step .child-primary').click()
    else: page.locator('.child-priorities input[aria-label="Read for ten minutes"]').check()
    page.wait_for_function("pwaChildDay.items.find(i=>i.id==='book').checked")
    if key == 'sprout':
        # Switching from the three-tab shell must restore adult labels, order
        # and tokens, and invalidate any child detail payload still in memory.
        page.evaluate("""()=>{
            membersData.push({id:'shell-adult',name:'Adult fixture',role:'parent',driver_id:'shell-driver'});
            selectedMemberId='shell-adult'; selectedDriverId='shell-driver'; currentView='drives'; applyRoleTabs();
        }""")
        assert page.locator('html').get_attribute('data-child-stage') is None
        adult_tabs = page.locator('#pwa-tab-bar > button:visible > span:first-of-type').all_text_contents()
        assert adult_tabs == ['Today','Plan','Household','Messages','More'], adult_tabs
        assert page.evaluate('pwaChildDay') is None


def check_child_day_navigation(page, key, calls, output):
    """Older children can browse directly from Today and return without Plan."""
    nav = page.locator('.child-day-nav')
    assert nav.is_visible()
    assert nav.evaluate('(e)=>e.getBoundingClientRect().bottom < innerHeight - 80')
    dates = page.evaluate('[-1,0,1].map(_mydayLocalDate)')
    nav.get_by_role('button', name='Next day', exact=True).click()
    page.wait_for_function('pwaChildDay.offset === 1 && !pwaChildPlan')
    assert nav.locator('strong').inner_text() == 'Tomorrow'
    assert 'Today, on your terms.' not in page.locator('.child-greeting').inner_text()
    assert page.locator('.child-priorities input:enabled').count() == 0
    assert page.locator('.child-all-routine').count() == 0
    assert any('date='+dates[2] in c for c in calls if isinstance(c, str))
    if output: Path(output, key+'-tomorrow.png').write_bytes(page.screenshot())
    # Today tab itself is a reliable reset, even without a view change.
    page.locator('#tab-myday').click()
    page.wait_for_function('pwaChildDay.offset === 0 && !pwaChildPlan')
    nav.get_by_role('button', name='Previous day', exact=True).click()
    page.wait_for_function('pwaChildDay.offset === -1')
    assert nav.locator('strong').inner_text() == 'Yesterday'
    assert any('date='+dates[0] in c for c in calls if isinstance(c, str))
    assert page.locator('.child-priorities input:enabled').count() == 0
    nav.get_by_role('button', name='Back to today', exact=True).click()
    page.wait_for_function('pwaChildDay.offset === 0')
    assert page.locator('.child-priorities input:enabled').count() > 0
    # Empty dates retain navigation and the explicit return path.
    page.route('**/api/members/'+key+'/day?*', lambda r:r.fulfill(json=dict(rides=[], due_soon=[], status_days=[])))
    nav.get_by_role('button', name='Next day', exact=True).click()
    page.wait_for_function('pwaChildDay.offset === 1 && pwaChildDay.rides.length === 0')
    assert page.get_by_text('No rides scheduled for this day.', exact=True).is_visible()
    page.unroute('**/api/members/'+key+'/day?*')
    nav.get_by_role('button', name='Back to today', exact=True).click()
    page.wait_for_function('pwaChildDay.offset === 0 && pwaChildDay.rides.length > 0')


def check_child_driver(page, output):
    """A real configured Copilot driver keeps the original scheduler actions."""
    page.wait_for_selector('.pwa-next')
    assert page.locator('html').get_attribute('data-child-stage') == 'copilot'
    assert page.locator('#tab-family').is_hidden()
    assert page.locator('.pwa-leg-row .pwa-row-main').count() > 0
    assert page.locator('.pwa-event-row.opacity-40').count() == 0
    assert page.locator('.pwa-next').is_visible()
    assert page.locator('.pwa-section-title button').first.inner_text() == 'My plan \u2192'
    if output: Path(output,'copilot-driving-light.png').write_bytes(page.screenshot())
    page.locator('.pwa-next button').click()
    page.wait_for_function("driveSheetData?.leg_id === 'init_soccer'")
    assert page.locator('#sheet-title').inner_text() == 'Your drive'
    check_profile_button(page, '#btn-start-drive')
    page.wait_for_timeout(350)
    if output: Path(output,'copilot-drive-sheet-light.png').write_bytes(page.screenshot())
    page.get_by_role('button',name='Close drive details',exact=True).click()
    page.wait_for_selector('#action-sheet',state='hidden')
    page.locator('#tab-myday').click()
    page.wait_for_selector('.child-drive-link')
    page.locator('.child-day-nav [data-day-action="next"]').click()
    page.wait_for_function('pwaChildDay.offset === 1')
    page.locator('#tab-myday').click()
    page.wait_for_function('pwaChildDay.offset === 0')
    page.locator('.child-drive-link').click()
    page.wait_for_selector('.pwa-next')
    page.locator('#tab-more').click()
    assert page.locator('#pwa-feature-list [data-feature="drives"]').is_visible()
    # The presentation cannot manufacture driving permission from the stage.
    page.evaluate("membersData.find(m=>m.id===selectedMemberId).capabilities.can_drive=false; applyRoleTabs(); pwaRenderDirectory()")
    assert page.locator('#pwa-feature-list [data-feature="drives"]').count() == 0
    page.locator('#tab-myday').click()
    page.wait_for_selector('.child-greeting')
    assert page.locator('.child-drive-link').count() == 0
