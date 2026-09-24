"""The shared editor lives in the habitat; draft changes remain drafts until saved."""
from pathlib import Path
from test_house_habitat_live import seed_habitat, live_app, ha_api, PETS

OUT = Path('../scratch/workbench-review')
EDITOR = "Alpine.$data(document.getElementById('pet-editor-panel'))"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed_habitat)
    assert served
    try:
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            page.set_default_timeout(20000)
            page.route('**/api/v2/chat/stream*', lambda r:r.fulfill(status=204,body=''))
            page.route('**/api/music/favorites*', lambda r:r.fulfill(json={'items':[]}))
            mutations=[]
            page.on('request',lambda r:mutations.append(r.url) if '/api/pets' in r.url and r.method != 'GET' else None)
            page.goto(served.url('house?compare=living&light=day'),wait_until='domcontentloaded')
            page.wait_for_function('window.chfHouseComparison?.readyMs > 0')
            page.evaluate("() => {window.chfMemberToken=async()=>''; window.promptConfirm=async()=>false;}")
            page.locator('#hybrid-room [data-card="pets"]:visible').click()
            page.wait_for_selector('#hybrid-room-frame[data-view="pets"][data-phase="detail"]')
            page.wait_for_function("!Alpine.$data(document.getElementById('house-life')).loading")
            page.get_by_role('button',name='Next critter',exact=True).click()
            assert page.locator('.habitat-plaque h2').inner_text() == 'Ember'
            panel=page.locator('#pet-editor-panel')

            def open_editor():
                page.get_by_role('button',name='Customize',exact=True).click()
                page.wait_for_function(EDITOR + '.show && !' + EDITOR + '.loading')
                page.wait_for_selector('body.habitat-editing')
                assert page.evaluate(EDITOR+'.workbench')

            def fit():
                assert page.evaluate("""() => {
                    const a=document.querySelector('.pet-editor-surface').getBoundingClientRect(),
                          b=document.getElementById('hybrid-detail-picture').getBoundingClientRect();
                    return ['x','y','width','height'].every(k=>Math.abs(a[k]-b[k])<1);
                }""")
                for selector in ['.pet-drawer','.pet-preview','.pet-nameplate']:
                    rect=panel.locator(selector).bounding_box()
                    assert rect and rect['x'] >= 0 and rect['y'] >= 0, (selector,rect)
                    assert rect['x']+rect['width'] <= page.viewport_size['width']+1, (selector,rect)
                    assert rect['y']+rect['height'] <= page.viewport_size['height']+1, (selector,rect)
                assert panel.locator('.pet-choices').bounding_box()['height'] >= 70

            open_editor()
            fit()
            original=panel.locator('.pet-preview').inner_html()
            panel.get_by_role('button',name='body: blob',exact=True).click()
            assert panel.locator('.pet-preview').inner_html() != original
            panel.get_by_role('button',name='Colour',exact=False).click()
            panel.locator('.pet-swatch[title="Mint"]').first.click()
            panel.get_by_role('textbox',name='Critter name').fill('Draft only')
            assert not mutations
            page.screenshot(path=str(OUT/'workbench-colors-day.png'))
            panel.get_by_role('button',name='Cancel',exact=True).click()
            page.wait_for_function("!document.body.classList.contains('habitat-editing')")
            assert page.locator('.habitat-plaque h2').inner_text() == 'Ember'
            open_editor()
            assert panel.locator('.pet-preview').inner_html() == original
            assert panel.get_by_role('textbox',name='Critter name').input_value() == 'Ember'
            page.screenshot(path=str(OUT/'workbench-parts-day.png'))
            panel.get_by_role('button',name='Train',exact=False).click()
            panel.get_by_role('button',name='Save training',exact=True).click()
            page.locator('#cc-alert-modal').get_by_role('button',name='OK',exact=True).click()
            page.wait_for_function('!'+EDITOR+'.saving')
            assert page.evaluate(EDITOR+'.pet.id') == PETS['Ember']['id']
            assert mutations == [served.url('api/pets/'+PETS['Ember']['id']+'/training')]
            mutations.clear()
            panel.get_by_role('button',name='Moves',exact=False).first.click()
            unknown=panel.locator('button').filter(has_text='XP').filter(visible=True)
            unknown.first.click()
            assert not mutations
            known_before=page.evaluate(EDITOR+'.pet.known_moves.length')
            page.evaluate("() => {window.promptConfirm=async()=>true;}")
            unknown.first.click()
            page.wait_for_function('!'+EDITOR+'.busyBuy')
            assert page.evaluate(EDITOR+'.pet.id') == PETS['Ember']['id']
            assert page.evaluate(EDITOR+'.pet.known_moves.length') == known_before+1
            assert mutations == [served.url('api/pets/'+PETS['Ember']['id']+'/learn')]
            mutations.clear()
            page.screenshot(path=str(OUT/'workbench-moves-day.png'))
            panel.get_by_role('button',name='Body',exact=False).first.click()
            # A rejected save keeps the draft and drawer open.
            endpoint='**/api/pets/'+PETS['Ember']['id']
            page.route(endpoint,lambda r:r.fulfill(status=409,json={'detail':'Try again'}))
            panel.get_by_role('textbox',name='Critter name').fill('Ember Glow')
            panel.get_by_role('button',name='Save',exact=True).click()
            page.wait_for_function('!'+EDITOR+'.saving')
            assert panel.is_visible()
            assert panel.get_by_role('textbox',name='Critter name').input_value() == 'Ember Glow'
            page.unroute(endpoint)
            # Dismiss alert if present, then commit through the real API.
            page.locator('#cc-alert-modal').get_by_role('button',name='OK',exact=True).click()
            panel.get_by_role('button',name='Save',exact=True).click()
            panel.wait_for(state='hidden')
            page.get_by_role('heading',name='Ember Glow',exact=True).wait_for()
            page.locator('#house-compare-light').select_option('night')
            page.wait_for_selector('#hybrid-detail[data-light="night"]')
            open_editor()
            for width,height,label in [(1400,1000,'night'),(390,844,'phone'),(390,667,'small-phone'),(844,390,'landscape')]:
                page.set_viewport_size({'width':width,'height':height})
                fit()
                page.screenshot(path=str(OUT/('workbench-'+label+'.png')))
                panel.get_by_role('button',name='Save',exact=True).focus()
                page.keyboard.press('Tab')
                assert panel.get_by_role('textbox',name='Critter name').evaluate('el=>el===document.activeElement')
                page.keyboard.press('Escape')
                panel.wait_for(state='hidden')
                open_editor()
            page.keyboard.press('Escape')
            # Cancel during a slow open must not revive the drawer on completion.
            pending=[]
            url=served.url('api/pets?member_id=k1&include_retired=true')
            body=page.request.get(url).json()
            page.route(url,lambda route:pending.append(route))
            page.get_by_role('button',name='Customize',exact=True).click()
            page.wait_for_function(EDITOR+'.loading')
            page.wait_for_timeout(100)
            assert pending
            page.keyboard.press('Escape')
            pending.pop().fulfill(json=body)
            page.unroute(url)
            page.wait_for_timeout(150)
            assert not panel.is_visible()
            assert not page.locator('body').evaluate("el=>el.classList.contains('habitat-editing')")
            # The ordinary editor remains available outside the habitat.
            page.locator('#hybrid-view-back').click()
            page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            page.evaluate("id=>window.openPetEditor({id:'k1',petId:id})",PETS['Ember']['id'])
            page.wait_for_function(EDITOR+'.show && !'+EDITOR+'.loading')
            assert not page.evaluate(EDITOR+'.workbench')
            assert panel.locator('.pet-preview').is_visible()
            assert panel.get_by_role('button',name='Save',exact=True).is_visible()
            page.keyboard.press('Escape')
            errors=[e for e in served.errors() if '409 (Conflict)' not in e]
            assert not errors, errors
            print('PASS: registered workbench, live drafts, cancel/reopen, selected-pet training, XP confirmation, save failure/retry, day/night and responsive keyboard controls',flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    main()
