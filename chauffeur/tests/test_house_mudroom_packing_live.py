"""Photographic mudroom packing and screensaver glance use live shared data."""
import datetime
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
from test_house_hybrid_live import live_app, ha_api, storage

OUT = Path(__file__).resolve().parents[2] / 'scratch/mudroom-packing'
START = datetime.datetime.now() + datetime.timedelta(hours=2)

def seed():
    storage.patch_settings({'house_hybrid_enabled': True, 'panel_idle_return_seconds': 0})
    storage.add_driver({'id':'parent','name':'Parent','group':'primary','priority_index':1})
    storage.add_prep_kit({'id':'soccer-kit','name':'Soccer','items':['Water bottle'],'enabled':True,'keywords':['soccer'],'per_person':False})
    storage.add_prep_kit({'id':'band-kit','name':'Band','items':['Sheet music'],'enabled':True,'keywords':['band'],'per_person':False})
    events=[]
    for i,(key,title) in enumerate([('soccer','Soccer practice'),('band','Band rehearsal'),('library','Library visit')]):
        start=START+datetime.timedelta(minutes=30*i)
        events.append({'id':key,'title':title,'start':start.isoformat(),'end':(start+datetime.timedelta(minutes=20)).isoformat(),'calendar_ids':[]})
    storage.set_cached_schedule({'events':events,'assignments':{e['id']:'parent' for e in events},'route_edges':{'parent':{'soccer':{'to_event':'band','travel_mins':5},'band':{'to_event':'library','travel_mins':5}}},'initial_edges':{},'final_edges':{},'cars':[],'car_assignments':{}})

def main():
    import main as app_main
    app_main.refresh_schedule_logic=lambda *a,**kw:None
    app_main.trigger_background_refresh=lambda *a,**kw:None
    ha_api.get_states=lambda *a,**kw:[];ha_api.get_state=lambda *a,**kw:None
    OUT.mkdir(parents=True,exist_ok=True)
    hero={'all_done':False,'next':{'title':'Soccer practice','at':START.strftime('%H:%M'),'driver':'Parent','start':START.isoformat(),'end':(START+datetime.timedelta(minutes=20)).isoformat(),'leave_at':(START-datetime.timedelta(minutes=15)).isoformat(),'travel_mins':15}}
    # Startup's legacy geocode migration clears schedule caches after five seconds.
    with patch('services.family_day.day_in_focus',return_value=START.date()), patch('services.migrations.run_all_migrations',new=AsyncMock()):
        served=live_app(seed)
        try:
            with served.browser(reduced_motion='reduce') as page:
                page.set_default_timeout(20000)
                page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=204,body=''))
                page.route('**/api/home_board?widgets=hero',lambda r:r.fulfill(status=200,content_type='application/json',body=json.dumps({'hero':hero})))
                page.goto(served.url('house?light=day'))
                page.wait_for_selector('#house-glance:visible')
                page.get_by_text('Soccer practice',exact=True).first.wait_for()
                assert page.locator('#house-glance .ss-time').inner_text()
                assert page.locator('#house-glance .ss-date').inner_text()
                assert page.locator('#house-glance .glance-next').evaluate('(el)=>{const sample=document.createElement("div");sample.innerHTML=HeroCard.html('+json.dumps(hero['next'])+',{compact:true});return el.innerHTML===sample.innerHTML}')
                assert page.locator('#house-glance').evaluate('el=>+getComputedStyle(el).zIndex>+getComputedStyle(document.getElementById("house-exterior")).zIndex')
                page.screenshot(path=str(OUT/'exterior.png'))
                page.evaluate('async()=>{await chfHybridGo("mudroom")}')
                try:
                    page.wait_for_selector('.mudroom-pack')
                except Exception:
                    page.screenshot(path=str(OUT/'failure.png'))
                    print('Packing failure:', page.evaluate('({mode:chfHouseMode(),host:document.getElementById("mudroom-packing").outerHTML})'),served.errors(),flush=True)
                    raise
                assert page.locator('#house-glance').is_hidden()
                assert page.locator('.mudroom-pack').evaluate_all('els=>new Set(els.map(e=>e.dataset.slot)).size')==2
                assert page.locator('.mudroom-pack').count()==2, 'one per activity, not one per outing or prep tile'
                bag=page.get_by_role('button',name='Soccer practice: 0 of 1 packed. Open packing list',exact=True)
                assert bag.get_attribute('data-ready')=='false'
                page.screenshot(path=str(OUT/'bags-open.png'))
                page.evaluate("const light=document.getElementById('house-compare-light');light.value='night';light.dispatchEvent(new Event('change'))")
                page.wait_for_selector('#hybrid-mudroom[data-light=night]')
                assert 'mudroom-packs-open-night.png' in bag.locator('.mudroom-pack-art').evaluate('el=>getComputedStyle(el).backgroundImage')
                page.screenshot(path=str(OUT/'bags-night.png'))
                page.evaluate("const light=document.getElementById('house-compare-light');light.value='day';light.dispatchEvent(new Event('change'))")
                page.wait_for_selector('#hybrid-mudroom[data-light=day]')
                bag.click()
                with page.expect_response('**/api/packing/claim') as saved:
                    page.locator('#pack-dialog-root [data-pack-item="soccer-kit:water bottle"]').click()
                assert saved.value.ok
                page.wait_for_selector('.mudroom-pack[data-ready=true]')
                assert storage.get_packing_claims(START.date().isoformat())
                assert page.locator('.pack-dialog-title').inner_text()=='Soccer practice'
                page.keyboard.press('Escape')
                assert page.evaluate('chfHouseMode()')=='mudroom'
                closed=page.get_by_role('button',name='Soccer practice: Packed. Open packing list',exact=True)
                assert closed.evaluate('el=>el===document.activeElement')
                assert 'mudroom-packs-closed-day.png' in closed.locator('.mudroom-pack-art').evaluate('el=>getComputedStyle(el).backgroundImage')
                page.screenshot(path=str(OUT/'bag-closed.png'))
                closed.click()
                with page.expect_response('**/api/packing/claim') as saved:
                    page.locator('#pack-dialog-root [data-pack-item="soccer-kit:water bottle"]').click()
                assert saved.value.ok
                page.wait_for_selector('.mudroom-pack[data-ready=false]')
                page.wait_for_function('document.querySelectorAll(".mudroom-pack[data-ready=true]").length===0')
                page.locator('#pack-dialog-root [data-pack-close]').click()
                # A real save from a second device reaches the bag through the shared feed.
                payload=page.request.get(served.url('api/packing/day')).json()
                outing=next(b for b in payload['blocks'] if b['kind']=='outing')
                response=page.request.post(served.url('api/packing/claim'),data={'outing_key':outing['key'],'item_key':'band-kit:sheet music','delta':1})
                assert response.ok
                page.evaluate('async()=>{await chfMudroomPacking.refresh()}')
                assert page.get_by_role('button',name='Band rehearsal: Packed. Open packing list').get_attribute('data-ready')=='true'
                for w,h in ((390,844),(844,390),(2560,1080)):
                    page.set_viewport_size({'width':w,'height':h})
                    page.wait_for_function('document.querySelectorAll(".mudroom-pack:not([hidden])").length===2')
                    for node in page.locator('.mudroom-pack:visible').all():
                        node.scroll_into_view_if_needed();box=node.bounding_box()
                        assert 0<=box['x'] and box['x']+box['width']<=w+1
                        assert 0<=box['y'] and box['y']+box['height']<=h-90
                    page.screenshot(path=str(OUT/f'bags-{w}.png'))
                    page.evaluate('chfHybridHome()')
                    page.wait_for_selector('#house-glance:visible')
                    for selector in ('.glance-clock','.glance-next'):
                        box=page.locator('#house-glance '+selector).bounding_box()
                        assert box and box['x']>=0 and box['x']+box['width']<=w+1 and box['y']>=0 and box['y']+box['height']<=h
                    page.screenshot(path=str(OUT/f'exterior-{w}.png'))
                    page.evaluate('async()=>{await chfHybridGo("mudroom")}')
                # Preparation for tomorrow also creates bags, with no four-bag cap.
                page.evaluate('async()=>{await chfMudroomPacking.refresh()}')
                overflow={'date':START.date().isoformat(),'blocks':[{'kind':'prep','key':'prep','tiles':[
                    {'key':'tile'+str(i),'for_key':'trip'+str(i),'event_id':'event'+str(i),'title':'Activity '+str(i),'start':START.isoformat(),
                     'groups':[{'kit':'Kit','items':[{'key':'item'+str(i),'label':'Bottle','needed':1,'packed':0}]}]}
                    for i in range(7)]}]}
                page.route('**/api/packing/day*',lambda r:r.fulfill(status=200,content_type='application/json',body=json.dumps(overflow)))
                page.set_viewport_size({'width':1400,'height':1000})
                page.evaluate('async()=>{await chfMudroomPacking.refresh()}')
                assert page.locator('.mudroom-pack').count()==7
                page.screenshot(path=str(OUT/'bag-styles.png'))
                page.set_viewport_size({'width':390,'height':844})
                seen=set()
                while True:
                    for button in page.locator('.mudroom-pack:visible').all():
                        button.click();seen.add(page.locator('.pack-dialog-title').inner_text())
                        page.keyboard.press('Escape')
                    more=page.get_by_role('button',name='Next backpacks',exact=True)
                    if more.is_disabled():break
                    more.click()
                assert len(seen)==7
                page.screenshot(path=str(OUT/'bags-overflow.png'))
                page.unroute('**/api/packing/day*')
                # Empty packing does not leave demonstration backpacks behind.
                storage.set_cached_schedule({'events':[],'assignments':{}})
                page.evaluate('async()=>{await chfMudroomPacking.refresh()}')
                assert page.locator('#mudroom-packing').is_hidden()
                page.evaluate('chfHybridHome()');hero['all_done']=True
                page.evaluate('document.dispatchEvent(new Event("chf-server-update"))')
                page.wait_for_selector('#house-glance .glance-next',state='hidden')
                assert page.locator('#house-glance .glance-clock').is_visible()
                assert not served.errors(),served.errors()
                print('PASS activity backpacks, shared claims, open/closed/reopen, remote updates, responsive layouts, exterior clock/hero and empty states')
        finally:served.stop()

if __name__=='__main__':main()
