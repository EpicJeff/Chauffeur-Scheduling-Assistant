"""Real battles in the registered habitat; replays never submit another fight."""
from pathlib import Path
from test_house_habitat_live import seed_habitat, live_app, ha_api, PETS
from test_house_hybrid_live import storage

OUT=Path('../scratch/arena-review')
B="Alpine.$data(document.getElementById('pet-battle-panel'))"


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    ha_api.get_states=lambda *a,**kw:[]
    ha_api.get_state=lambda *a,**kw:None
    served=live_app(seed_habitat)
    import main as app_main
    app_main._notify_challenge=lambda *a,**kw:False
    app_main._notify_challenge_answered=lambda *a,**kw:False
    try:
        with served.browser(reduced_motion='reduce',has_touch=True) as page:
            page.set_default_timeout(20000)
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=204,body=''))
            page.route('**/api/music/favorites*',lambda r:r.fulfill(json={'items':[]}))
            posts=[]
            page.on('request',lambda r:posts.append(r.url) if '/api/pets/' in r.url and r.method=='POST' else None)
            page.goto(served.url('house?compare=living&light=day'),wait_until='domcontentloaded')
            page.wait_for_function('window.chfHouseComparison?.readyMs > 0')
            page.evaluate("() => {window.chfMemberToken=async()=>'';}")
            page.locator('#hybrid-room [data-card="pets"]:visible').click()
            page.wait_for_selector('#hybrid-room-frame[data-view="pets"][data-phase="detail"]')
            page.wait_for_function("!Alpine.$data(document.getElementById('house-life')).loading")
            page.get_by_role('button',name='Next critter',exact=True).click()
            page.get_by_role('button',name='Battle',exact=True).click()
            page.wait_for_function(B+'.show && !'+B+'.busy')
            panel=page.locator('#pet-battle-panel')
            assert page.evaluate(B+'.pet.id')==PETS['Ember']['id']
            assert page.evaluate(B+'.habitat')
            assert not posts

            def cover():
                assert page.evaluate("""() => {
                    const p=document.getElementById('hybrid-detail-picture').getBoundingClientRect();
                    const s=document.querySelector('.pb-surface').getBoundingClientRect();
                    return p.x<=1 && p.y<=1 && p.right>=innerWidth-1 && p.bottom>=innerHeight-1 &&
                        ['x','y','width','height'].every(k=>Math.abs(p[k]-s[k])<1);
                }""")

            cover()
            # Real panel theme rules must not paint over the photographed scene.
            for theme in ('light','dark'):
                page.evaluate('(theme)=>{document.documentElement.setAttribute("data-panel", "");document.documentElement.dataset.panelTheme=theme;}',theme)
                assert page.locator('#pet-battle-panel').evaluate('e=>getComputedStyle(e).backgroundColor==="rgba(0, 0, 0, 0)" && getComputedStyle(e).backgroundImage==="none"')
                page.screenshot(path=str(OUT/('theme-'+theme+'.png')))
            page.evaluate('()=>{document.documentElement.removeAttribute("data-panel");document.documentElement.removeAttribute("data-panel-theme");}')
            page.screenshot(path=str(OUT/'arena-pick.png'))
            panel.get_by_role('button',name='Practice against',exact=False).first.click()
            page.wait_for_function(B+".stage === 'fight'")
            assert len(posts)==1
            assert page.evaluate(B+'.replay.a.name')=='Ember'
            page.screenshot(path=str(OUT/'arena-fight.png'))
            panel.get_by_role('button',name='Skip',exact=True).click()
            page.wait_for_function(B+".stage === 'result'")
            assert page.evaluate(B+'.effects.length')==0
            hp=page.evaluate(B+'.hp')
            page.wait_for_timeout(500)
            assert page.evaluate(B+'.hp')==hp
            page.screenshot(path=str(OUT/'arena-result.png'))
            panel.get_by_role('button',name='Again',exact=True).click()
            page.wait_for_function(B+'.past.length > 0')
            balance=page.request.get(served.url('api/pets/xp?member_id=k1')).json()['balance']
            panel.get_by_role('button',name='Watch',exact=False).first.click()
            page.wait_for_function(B+".stage === 'fight'")
            assert page.evaluate(B+'.isReplay')
            panel.get_by_role('button',name='Skip',exact=True).click()
            assert page.evaluate(B+'.awarded')==0
            assert page.request.get(served.url('api/pets/xp?member_id=k1')).json()['balance']==balance
            assert len(posts)==1
            panel.get_by_role('button',name='Train',exact=True).click()
            page.wait_for_selector('body.habitat-editing')
            assert page.evaluate("Alpine.$data(document.getElementById('pet-editor-panel')).pet.id")==PETS['Ember']['id']
            page.keyboard.press('Escape')
            page.locator('#house-compare-light').select_option('night')
            page.wait_for_selector('#hybrid-detail[data-light="night"]')
            page.get_by_role('button',name='Battle',exact=True).click()
            page.wait_for_function('!'+B+'.busy')
            for width,height,label in [(390,844,'phone'),(844,390,'landscape')]:
                page.set_viewport_size({'width':width,'height':height})
                cover()
                panel.get_by_role('button',name='Practice against',exact=False).first.click()
                page.wait_for_function(B+".stage === 'fight'")
                for fighter in ['.pb-mine','.pb-theirs']:
                    box=panel.locator(fighter).bounding_box()
                    assert box['x']>=0 and box['y']>=60 and box['x']+box['width']<=width,(fighter,box)
                page.screenshot(path=str(OUT/('arena-'+label+'.png')))
                panel.get_by_role('button',name='Skip',exact=True).click()
                panel.get_by_role('button',name='Done',exact=True).focus()
                page.keyboard.press('Tab')
                assert panel.get_by_role('button',name='Again',exact=True).evaluate('el=>document.activeElement===el')
                panel.get_by_role('button',name='Again',exact=True).click()
            # Stop every pending hit animation as well as the turn timer.
            panel.get_by_role('button',name='Practice against',exact=False).first.click()
            page.wait_for_function(B+".stage === 'fight'")
            panel.get_by_role('button',name='Leave',exact=True).click()
            assert page.evaluate(B+'.effects.length')==0
            assert page.locator('#house-habitat').evaluate('el=>document.activeElement===el')
            page.wait_for_timeout(1100)
            assert not panel.is_visible()
            # Incoming family invitation uses the stored combatants, even with
            # another of this member's pets selected when accepting.
            storage.create_pet_challenge('k2','k1')
            page.get_by_role('button',name='Battle',exact=True).click()
            page.wait_for_function('!'+B+'.busy')
            panel.get_by_role('button',name='Fight!',exact=True).click()
            page.wait_for_function(B+".stage === 'fight'")
            assert page.evaluate(B+'.replay.a.name')=='Sprout'
            assert '<svg' in page.evaluate(B+'.sceneMine')
            assert page.evaluate(B+'.replay.level_matched')
            panel.get_by_role('button',name='Skip',exact=True).click()
            panel.get_by_role('button',name='Train',exact=True).click()
            page.wait_for_function("Alpine.$data(document.getElementById('pet-editor-panel')).pet?.id === '"+PETS['Sprout']['id']+"'")
            page.keyboard.press('Escape')
            page.get_by_role('button',name='Battle',exact=True).click()
            page.wait_for_function('!'+B+'.busy')
            # A late response after Leave cannot start a hidden replay or
            # overwrite the next open's state. This response is a fixture;
            # all normal battle paths above use the real server.
            pending=[]
            page.route('**/api/pets/battle',lambda r:pending.append(r))
            panel.get_by_role('button',name='Practice against',exact=False).first.click()
            page.wait_for_function(B+'.busy')
            page.wait_for_timeout(100)
            assert pending
            panel.get_by_role('button',name='Close arena',exact=True).click()
            page.get_by_role('button',name='Battle',exact=True).click()
            page.wait_for_function('!'+B+'.busy')
            pending.pop().fulfill(json={'replay':None,'awarded':0})
            page.wait_for_timeout(250)
            assert page.evaluate(B+'.stage')=='pick'
            assert page.evaluate(B+'.effects.length')==0
            page.unroute('**/api/pets/battle')
            panel.get_by_role('button',name='Close arena',exact=True).click()
            page.locator('#hybrid-view-back').click()
            page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            page.evaluate("id=>window.openPetBattle({id:'k1',petId:id})",PETS['Ember']['id'])
            page.wait_for_function(B+'.show && !'+B+'.busy')
            assert not page.evaluate(B+'.habitat')
            assert panel.get_by_role('button',name='Practice against',exact=False).first.is_visible()
            page.keyboard.press('Escape')
            assert not served.errors(),served.errors()
            print('PASS: actual practice and family fights, selected pet, replay without POST, timer cleanup, training handoff, full-bleed geometry, day/night, phone/landscape and keyboard',flush=True)
    finally:
        served.stop()


if __name__=='__main__':
    main()
