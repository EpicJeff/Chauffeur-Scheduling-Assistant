"""Critter habitat with real saved SVGs, shared editor/battle and isolated storage."""
from pathlib import Path
from test_house_hybrid_live import seed, live_app, ha_api, storage

OUT = Path('../scratch/habitat-review')
PETS = {}


def seed_habitat():
    seed()
    storage.grant_pet_xp('k1', storage.PET_SLOT_COST * 3, 'grant')
    storage.buy_pet_slot('k1')
    storage.buy_pet_slot('k1')
    PETS['Sprout'] = storage.create_pet('k1', 'Sprout', {'body':'blob','top':'nub'}, {'base_color':'Mint','accent_color':'Lime'}, 'grove')['pet']
    PETS['Ember'] = storage.create_pet('k1', 'Ember', {'body':'tower','top':'horns'}, {'base_color':'Apricot','accent_color':'Rose'}, 'ember')['pet']
    PETS['Pebble'] = storage.create_pet('k2', 'Pebble', {'body':'block','top':'nub'}, {'base_color':'Periwinkle','accent_color':'Sky'})['pet']
    storage.grant_pet_xp('k2', storage.PET_SLOT_COST, 'grant')


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
            page.evaluate("() => { window.gates=[]; window.chfMemberToken=async(m)=>{gates.push(m);return null;}; localStorage.setItem('chauffeur_pet_guide_seen_k1','1'); }")

            def enter():
                page.locator('#hybrid-room [data-card="pets"]:visible').click()
                page.wait_for_selector('#hybrid-room-frame[data-view="pets"][data-phase="detail"]')
                page.wait_for_function("!Alpine.$data(document.getElementById('house-life')).loading")

            def select(name):
                for _ in range(12):
                    if page.locator('.habitat-plaque h2').inner_text() == name:
                        return
                    page.get_by_role('button',name='Next critter',exact=True).click()
                raise AssertionError('Missing critter: ' + name)

            def registration():
                assert page.evaluate("() => { const a=document.getElementById('house-habitat').getBoundingClientRect(), b=document.getElementById('hybrid-detail-picture').getBoundingClientRect();return ['x','y','width','height'].every(k=>Math.abs(a[k]-b[k])<1);}")
                assert page.locator('#hybrid-room-frame').evaluate("el=>el.getBoundingClientRect().x===0 && el.getBoundingClientRect().y===0")
                assert page.locator('#hybrid-room-frame').evaluate('el=>el.scrollTop===0 && el.scrollLeft===0')

            enter()
            select('Ember')
            assert page.locator('.habitat-center svg').count() == 1
            assert 'Maya' in page.locator('.habitat-plaque').inner_text()
            registration()
            page.screenshot(path=str(OUT/'habitat-day-desktop.png'))
            page.get_by_role('button',name='Customize',exact=True).click()
            page.wait_for_function('gates.length===1')
            assert not page.locator('#pet-editor-panel').is_visible()
            assert page.evaluate('gates[0].petId') == PETS['Ember']['id']
            assert not mutations
            # Exercise the real editor after the same member gate grants access.
            page.evaluate("() => { window.chfMemberToken=async(m)=>{gates.push(m);return '';}; }")
            page.get_by_role('button',name='Customize',exact=True).click()
            page.wait_for_function("Alpine.$data(document.getElementById('pet-editor-panel')).name === 'Ember' && !Alpine.$data(document.getElementById('pet-editor-panel')).loading")
            assert page.locator('#pet-editor-panel input[placeholder="Name your critter"]').input_value() == 'Ember'
            page.keyboard.press('Escape')
            page.locator('#pet-editor-panel').wait_for(state='hidden')
            assert page.locator('#house-habitat').evaluate('(el)=>document.activeElement===el')
            assert page.locator('#hybrid-room-frame').get_attribute('data-view') == 'pets'
            page.get_by_role('button',name='Battle',exact=True).click()
            page.wait_for_function("Alpine.$data(document.getElementById('pet-battle-panel')).pet?.name === 'Ember'")
            page.locator('#pet-battle-panel').wait_for(state='visible')
            battle_control=page.locator('#pet-battle-panel [title="Train & customise"]')
            battle_control.focus()
            page.evaluate("window.dispatchEvent(new CustomEvent('pet-battle-done'))")
            page.wait_for_function("!Alpine.$data(document.getElementById('house-life')).loading")
            assert battle_control.evaluate('(el)=>document.activeElement===el')
            page.keyboard.press('Escape')
            page.locator('#pet-battle-panel').wait_for(state='hidden')
            # New slot for somebody who already has two creatures must open an egg.
            page.evaluate("Alpine.$data(document.getElementById('house-habitat')).selectedKey='k1:empty'")
            page.get_by_role('button',name='Hatch a critter',exact=True).click()
            page.wait_for_function("Alpine.$data(document.getElementById('pet-editor-panel')).show && !Alpine.$data(document.getElementById('pet-editor-panel')).loading")
            assert page.evaluate("Alpine.$data(document.getElementById('pet-editor-panel')).pet") is None
            assert page.get_by_role('button',name='Hatch!',exact=True).is_visible()
            page.keyboard.press('Escape')
            page.evaluate("() => { window.buyAsked=0;window.promptConfirm=async()=>{buyAsked++;return false;};Alpine.$data(document.getElementById('house-habitat')).selectedKey='k2:buy'; }")
            page.get_by_role('button',name='Another slot',exact=False).click()
            page.wait_for_function('buyAsked===1')
            assert not mutations
            select('Ember')
            page.get_by_role('button',name='Customize',exact=True).click()
            page.wait_for_function("!Alpine.$data(document.getElementById('pet-editor-panel')).loading")
            page.locator('#pet-editor-panel input[placeholder="Name your critter"]').fill('Ember Glow')
            page.get_by_role('button',name='Save',exact=True).click()
            page.get_by_role('heading',name='Ember Glow',exact=True).wait_for()
            assert mutations == [served.url('api/pets/' + PETS['Ember']['id'])]
            mutations.clear()
            page.evaluate("Alpine.$data(document.getElementById('house-life')).t.data.interactive=false")
            gates_before=page.evaluate('gates.length')
            page.locator('.habitat-center').click()
            assert page.evaluate('gates.length') == gates_before
            assert not page.get_by_role('button',name='Customize',exact=True).is_visible()
            page.evaluate("Alpine.$data(document.getElementById('house-life')).t.data.interactive=true")
            page.locator('#house-compare-light').select_option('night')
            page.wait_for_selector('#hybrid-detail[data-light="night"]')
            registration()
            page.screenshot(path=str(OUT/'habitat-night-desktop.png'))
            page.set_viewport_size({'width':390,'height':844})
            registration()
            page.screenshot(path=str(OUT/'habitat-phone.png'))
            previous=page.locator('.habitat-plaque h2').inner_text()
            page.get_by_role('button',name='Next critter',exact=True).tap()
            assert page.locator('.habitat-plaque h2').inner_text() != previous
            swipe_before=page.locator('.habitat-plaque h2').inner_text()
            cdp=page.context.new_cdp_session(page)
            cdp.send('Input.dispatchTouchEvent', {'type':'touchStart','touchPoints':[{'x':300,'y':440}]})
            cdp.send('Input.dispatchTouchEvent', {'type':'touchMove','touchPoints':[{'x':100,'y':440}]})
            cdp.send('Input.dispatchTouchEvent', {'type':'touchEnd','touchPoints':[]})
            assert page.locator('.habitat-plaque h2').inner_text() != swipe_before
            assert not page.locator('#pet-editor-panel').is_visible()
            page.locator('#house-habitat').evaluate('el=>el.focus({preventScroll:true})')
            page.keyboard.press('ArrowLeft')
            page.set_viewport_size({'width':844,'height':390})
            registration()
            page.screenshot(path=str(OUT/'habitat-landscape-phone.png'))
            page.get_by_role('button',name='Next critter',exact=True).tap()
            page.locator('#hybrid-view-back').click()
            page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            # Failed, empty and read-only projections cannot accidentally invoke mutations.
            page.route('**/api/home_board?widgets=pets', lambda r:r.fulfill(body='invalid',content_type='application/json'))
            enter()
            page.get_by_role('button',name='Try again',exact=True).wait_for()
            page.unroute('**/api/home_board?widgets=pets')
            page.route('**/api/home_board?widgets=pets', lambda r:r.fulfill(json={'tiles':[{'type':'pets','data':{'members':[],'interactive':False}}]}))
            page.get_by_role('button',name='Try again',exact=True).click()
            page.get_by_role('heading',name='A little world awaits').wait_for()
            assert not page.get_by_role('button',name='Customize',exact=True).is_visible()
            assert not mutations
            assert not served.errors(), served.errors()
            print('PASS: saved creatures, selected-pet editor/battle, PIN cancellation, hatch/buy intent, refresh, day/night, touch/keyboard, camera registration and errors/empty',flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    main()
