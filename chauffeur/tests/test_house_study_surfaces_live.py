"""Own-object close-ups, real in-room writes, geography and bounded parent data."""
import argparse
import math
from pathlib import Path
from test_house_connected_live import seed, live_app, ha_api, storage
from services import study, vitals, maps
import main as app_main


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True)
    out=Path(parser.parse_args().out).resolve();out.mkdir(parents=True,exist_ok=True)
    ha_api.get_states=lambda *a,**kw:[];ha_api.get_state=lambda *a,**kw:None
    served=live_app(seed)
    try:
        from datetime import datetime
        original=vitals.read
        for ready,worse,state in [(False,2,'unknown'),(True,0,'thriving'),(True,1,'drooping'),(True,2,'wilting')]:
            vitals.read=lambda *a,**kw:{'ready':ready,'household':[{'label':str(i),'current':2,'worse':True} for i in range(worse)]}
            assert study._window(datetime.now(),None)['plant_state']==state
        vitals.read=original
        storage.set_trip_metadata('demo-unlocated',{'title':'Undecided escape','location':'Unresolved destination','audience':'parents'})
        storage.set_cached_geocode('Unresolved destination',float('nan'),5)
        unknown=next(t for t in study._map(datetime.now(),None)['trips'] if t['event_id']=='demo-unlocated')
        assert unknown['lat'] is None and unknown['lon'] is None
        with served.browser(reduced_motion='reduce') as page:
            page.set_default_timeout(20000)
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=204,body=''))
            def mode(name):page.wait_for_function('(n)=>chfHouseMode()===n',arg=name)
            def enter(key):
                host='.utility-shortcuts' if page.viewport_size['width']<701 else '.utility-hotspots'
                page.locator(f'#hybrid-study {host} [data-card={key}]').click()
                page.wait_for_selector('#hybrid-study[data-phase=detail]')
            def back():
                page.locator('#hybrid-study .utility-back').click();page.wait_for_function('!history.state?.chfUtilityView')
            def saved():page.wait_for_function("document.querySelector('.study-feedback')?.textContent && document.querySelector('.study-feedback').textContent!=='Saving…'")
            page.goto(served.url('house?compare=exterior&scene=living&light=day'));mode('living')
            page.locator('#hybrid-walkthrough [data-room=study]').click()
            page.wait_for_selector('#cc-input-field:visible');page.fill('#cc-input-field','1234');page.click('#cc-input-ok-btn');mode('study')
            token=page.evaluate('chfHouseParent().token')
            enter('map')
            pins=page.locator('.study-map-pin');assert pins.count()==3
            home=page.get_by_role('img',name='Home',exact=True)
            assert home.count()==1
            assert math.isclose(float(home.evaluate('n=>parseFloat(n.style.left)')),(-104.9903+180)/360*100,abs_tol=.0001)
            assert math.isclose(float(home.evaluate('n=>parseFloat(n.style.top)')),(90-39.7392)/180*100,abs_tol=.0001)
            threads=page.locator('.study-map-strings path');assert threads.count()==3
            assert page.locator('.study-map-strings').evaluate("s=>getComputedStyle(s).pointerEvents==='none'")
            endpoints=threads.evaluate_all('ps=>ps.map(p=>{const a=p.getPointAtLength(0),b=p.getPointAtLength(p.getTotalLength());return [a.x,a.y,b.x,b.y]})')
            for start_x,start_y,_,_ in endpoints:
                assert math.isclose(start_x,(-104.9903+180)/360*1000,abs_tol=.001)
                assert math.isclose(start_y,(90-39.7392)/180*500,abs_tol=.001)
            assert any(math.isclose(x,(2.3522+180)/360*1000,abs_tol=.001) and math.isclose(y,(90-48.8566)/180*500,abs_tol=.001) for _,_,x,y in endpoints)
            paris=page.get_by_role('link',name='Autumn in Paris · Paris, France',exact=True).first
            assert 'event_id=demo-trip-paris' in paris.get_attribute('href')
            assert math.isclose(float(paris.evaluate('n=>parseFloat(n.style.left)')), (2.3522+180)/360*100,abs_tol=.0001)
            assert math.isclose(float(paris.evaluate('n=>parseFloat(n.style.top)')), (90-48.8566)/180*100,abs_tol=.0001)
            page.get_by_text('Undecided escape · Unresolved destination — location needed').wait_for()
            original_geocode=maps.geocode_address
            def locate(address):storage.set_cached_geocode(address,10,20);return (10,20)
            maps.geocode_address=locate
            page.get_by_role('button',name='Locate destination',exact=True).click();page.wait_for_function("document.querySelectorAll('.study-map-pin').length===4")
            assert page.locator('.study-map-strings path').count()==4
            maps.geocode_address=original_geocode
            page.screenshot(path=str(out/'world-map.png'));back()
            enter('desk');page.get_by_text('Write down questions for the teacher',exact=True).wait_for()
            page.get_by_role('button',name='Mark done',exact=True).first.click();saved()
            assert next(r for r in storage.get_mind_insights() if r['id']=='demo-plan')['plan_json']['steps'][0]['status']=='done'
            page.screenshot(path=str(out/'plan-action.png'));back()
            enter('binders');page.get_by_text('A steady beginning',exact=True).wait_for()
            page.get_by_label('Minutes practised',exact=True).fill('17')
            page.get_by_label('Session note',exact=True).fill('Relaxed hands, steady beat.')
            page.locator('.study-binders h2').click()
            page.evaluate("chfUtilityRooms.ready('study')")
            assert page.get_by_label('Session note',exact=True).input_value()=='Relaxed hands, steady beat.'
            page.get_by_role('button',name='Log practice',exact=True).click();saved()
            assert storage.get_program('demo-piano')['sessions'][-1]['minutes']==17
            page.get_by_role('button',name='Pause program',exact=True).click();page.get_by_role('button',name='Resume program',exact=True).wait_for()
            assert storage.get_program('demo-piano')['state']=='paused'
            page.get_by_role('button',name='Resume program',exact=True).click();page.get_by_role('button',name='Pause program',exact=True).wait_for()
            page.screenshot(path=str(out/'program-action.png'));back()
            enter('tray');page.locator('.study-sort select').select_option('title')
            assert page.locator('.study-tray h3').inner_text()=='Library renewal reminder'
            page.get_by_role('button',name='Next →',exact=True).click()
            assert page.locator('.study-tray h3').inner_text()=='School field trip permission slip'
            page.get_by_label('Title',exact=True).fill('Sign museum permission slip')
            page.get_by_role('button',name='Approve & file',exact=True).click();saved()
            assert storage.get_proposal('demo-intake-0')['status']=='approved'
            assert any(t['title']=='Sign museum permission slip' for t in storage.get_household_tasks())
            page.screenshot(path=str(out/'intake-action.png'));back()
            enter('contracts')
            left=page.locator('.study-agreement-page').first.bounding_box();right=page.locator('.study-agreement-page').last.bounding_box()
            assert right['x']>left['x']+left['width']
            page.screenshot(path=str(out/'agreements.png'))
            page.get_by_role('button',name='Close agreement',exact=True).click();saved()
            assert storage.get_deal('demo-agreement')['state']=='dead';back()
            enter('stickies');page.get_by_role('button',name='Mark handled',exact=True).click();saved()
            assert storage.get_finding('demo-finding')['state']=='done';back()
            # Plant state changes are reflected both in the room and its own close-up.
            original_window=study.state
            for state in ('thriving','drooping','wilting','unknown'):
                def with_plant(*args,**kw):
                    data=original_window(*args,**kw);data['furniture']['window'].update(ready=state!='unknown',plant_state=state);return data
                study.state=with_plant
                page.evaluate("chfUtilityRooms.ready('study')")
                enter('window');page.wait_for_selector(f'.study-window[data-plant-state={state}]')
                page.screenshot(path=str(out/f'plant-{state}.png'));back()
            study.state=original_window
            # No style collision, offscreen controls, or pinch-to-read on phones.
            page.set_viewport_size({'width':390,'height':844})
            for key in ('tray','contracts','map','gauges','window'):
                enter(key);page.screenshot(path=str(out/f'{key}-phone.png'))
                if key=='window':page.get_by_role('button',name='Read baseline',exact=True).click();page.screenshot(path=str(out/'baseline-phone.png'))
                if key=='gauges':page.get_by_role('button',name='Research →',exact=True).click();page.screenshot(path=str(out/'research-phone.png'))
                back()
            # Live private content disappears on expiry, including late network results.
            enter('binders')
            page.route('**/api/programs/demo-piano/session',lambda r:r.fulfill(status=500,json={'detail':'Practice could not save. Try again.'}))
            page.get_by_role('button',name='Log practice',exact=True).click()
            page.get_by_text('Practice could not save. Try again.',exact=True).wait_for()
            assert page.get_by_role('button',name='Log practice',exact=True).is_enabled()
            assert len(storage.get_program('demo-piano')['sessions'])==1
            page.unroute('**/api/programs/demo-piano/session')
            pending=[]
            page.route('**/api/programs/demo-piano/session',lambda r:pending.append(r))
            page.get_by_role('button',name='Log practice',exact=True).click()
            page.wait_for_function("document.querySelector('.study-feedback')?.textContent==='Saving…'")
            assert pending
            page.evaluate("()=>{const s=JSON.parse(sessionStorage.getItem('chauffeur_house_parent'));s.expires=Date.now()-1;sessionStorage.setItem('chauffeur_house_parent',JSON.stringify(s));}")
            mode('living');assert not page.locator('#study-controls').inner_text()
            pending[0].fulfill(status=200,json={'status':'success','message':'Late private result'})
            page.wait_for_function("!document.querySelector('#study-controls').textContent")
            assert not page.evaluate('chfUtilityProbe().privateLoaded')
            assert not storage.get_member_by_token(token)
            # Chromium reports the intentionally injected save failure once.
            expected='Failed to load resource: the server responded with a status of 500 (Internal Server Error)'
            assert served.errors().count(expected)==1,served.errors()
            assert not [e for e in served.errors() if e!=expected],served.errors()
            print('PASS: real Study writes; paper sorting; book pages; trip coordinate projection/lookup; four plant states; mobile; expiry')
    finally:served.stop()


if __name__=='__main__':main()
