"""Photographic kitchen: shared live cards, registration, light and navigation."""
import argparse
import json
import io
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageStat
from test_house_hybrid_live import seed as base_seed, live_app, ha_api, storage


def surface_fixtures(page):
    # Media and forecasts are fixtures; household shopping mutations use the real API.
    moments=[{'id':str(i),'body':f'Family photograph {i+1}','event_title':'Test album',
              'media_url':f'/static/house_hybrid/exterior-orbit/view-{i}.jpg','kind':'image','sender_name':'Family'} for i in range(6)]
    data={'moments':moments,'interactive':True}
    page.route('**/api/home_board?widgets=moments',lambda r:r.fulfill(json={'tiles':[{'type':'moments','data':data}]}))
    days=[{'day':d,'emoji':e,'hi':h,'lo':10,'rain':r} for d,e,h,r in [('Thu','☀️',24,0),('Fri','🌧️',18,85),('Sat','☁️',20,20),('Sun','☀️',23,0),('Mon','☀️',24,0)]]
    page.route('**/api/home_board?widgets=weather',lambda r:r.fulfill(json={'tiles':[{'type':'weather','data':{'days':days}}]}))
    day=datetime.now().strftime('%Y-%m-')+'15'
    page.route('**/api/schedule?*',lambda r:r.fulfill(json={'events':[{'id':'wall-test','title':'Family picnic','start':day+'T12:00:00','end':day+'T14:00:00','calendar_ids':[]}],'assignments':{}}))
    return data


def seed():
    base_seed()
    storage.dishes_table.insert({'id':'kitchen-soup','name':'Tomato soup','short_name':'Tomato soup','active':True,'hands_on_mins':15,'total_mins':30,'category_ids':[]})
    groceries=storage.get_shopping_lists()
    list_id=groceries[0]['id'] if groceries else 'kitchen-groceries'
    if not groceries:storage.add_shopping_list({'id':list_id,'name':'Groceries','is_default':True})
    storage.shopping_items_table.insert({'id':'kitchen-milk','name':'Oat milk','list_id':list_id,'is_checked':False,'created_at':1})


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True)
    out=Path(parser.parse_args().out).resolve();out.mkdir(parents=True,exist_ok=True)
    ha_api.get_states=lambda *a,**kw:[];ha_api.get_state=lambda *a,**kw:None
    served=live_app(seed);assert served
    try:
        with served.browser(reduced_motion='reduce',has_touch=True) as page:
            page.set_default_timeout(20000)
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=204,body=''))
            page.route('**/api/music/favorites*',lambda r:r.fulfill(status=200,content_type='application/json',body='{"items":[]}'))
            moment_data=surface_fixtures(page)
            payload={'window':{'night':False,'cond':'sunny'},'counter':{'count':1}}
            page.route('**/api/house/state*',lambda r:r.fulfill(status=200,content_type='application/json',body=json.dumps(payload)))
            def mode(value):page.wait_for_function('(m)=>window.chfExteriorProbe?.().mode===m',arg=value)
            def view(value):page.wait_for_function('(v)=>window.chfKitchenProbe?.().view===v',arg=value)
            def full_screen():
                assert page.locator('#kitchen-detail img.is-active').evaluate('''el=>{
                    const r=el.getBoundingClientRect();
                    return r.left<=1 && r.top<=1 && r.right>=innerWidth-1 && r.bottom>=innerHeight-1
                      && Math.abs(r.width/r.height-1.5)<.001;
                }'''), 'The actual close-up photograph must cover every viewport edge without stretching'
                assert page.locator('#kitchen-detail').evaluate('el=>getComputedStyle(el).backgroundImage==="none" && getComputedStyle(el,"::before").content==="none"')
            def open_card(key):
                host='#kitchen-shortcuts' if page.viewport_size['width']<701 else '#kitchen-hotspots'
                page.locator(host+f' [data-card="{key}"]').click()
                page.wait_for_function('(k)=>chfKitchenProbe().phase==="detail" && (k==="moments" || (Alpine.$data(document.getElementById("house-life")).active===k && !Alpine.$data(document.getElementById("house-life")).loading))',arg=key)
                full_screen()
            page.goto(served.url('house?compare=exterior&light=day'))
            page.wait_for_function('window.chfExteriorProbe?.().ready')
            assert page.locator('#hybrid-kitchen [data-kitchen-room=day]').get_attribute('src') is None
            page.locator('#exterior-kitchen-enter').click()
            assert page.locator('#exterior-kitchen-marker').get_attribute('aria-expanded')=='true'
            page.locator('.house-marker-feature[data-preview=lists]').click()
            page.wait_for_selector('.house-life-panel:visible');mode('exterior')
            page.get_by_role('button',name='Close and return to house',exact=True).click()
            page.locator('#exterior-kitchen-marker').click();mode('kitchen')
            assert 'scene=kitchen' in page.url
            assert page.locator('#house-life').evaluate('el=>el.parentNode.id')=='kitchen-controls'
            assert not page.evaluate('chfEffectsProbe().running')
            assert page.locator('#kitchen-steam').get_attribute('src') is None
            page.emulate_media(reduced_motion='no-preference')
            page.wait_for_function('chfKitchenEffectsProbe().frames>3')
            assert page.locator('#kitchen-steam').evaluate('''v=>{
                const c=document.createElement('canvas');c.width=v.videoWidth;c.height=v.videoHeight;
                const ctx=c.getContext('2d');ctx.drawImage(v,0,0);
                const data=ctx.getImageData(0,0,c.width,c.height).data;
                let clear=0,visible=0;
                for(let i=3;i<data.length;i+=4){if(data[i]===0)clear++;if(data[i]>20)visible++;}
                return v.videoWidth===384 && v.videoHeight===576 &&
                    getComputedStyle(v).filter==='none' && clear>c.width*c.height*.5 && visible>500;
            }'''), 'Steam must decode at full resolution with visible wisps and native transparency'
            assert not page.evaluate('chfEffectsProbe().running')
            page.locator('#kitchen-effects-toggle').uncheck()
            page.wait_for_function('!chfKitchenEffectsProbe().running')
            page.locator('#kitchen-effects-toggle').check()
            page.wait_for_function('chfKitchenEffectsProbe().running')
            page.locator('#kitchen-steam').evaluate('v=>{v.currentTime=v.duration-.15}')
            page.wait_for_function('document.getElementById("kitchen-steam").currentTime<1')
            # Keep visible-steam evidence at wall and touch sizes in both lights.
            for light in ('day','night'):
                page.locator('#house-compare-light').select_option(light)
                page.wait_for_function('(light)=>chfKitchenProbe().light===light',arg=light)
                for width,height in ((1400,900),(844,390)):
                    page.set_viewport_size({'width':width,'height':height})
                    page.wait_for_function('chfKitchenEffectsProbe().running')
                    page.screenshot(path=str(out/f'steam-{light}-{width}.png'))
            page.set_viewport_size({'width':1400,'height':900})
            page.locator('#house-compare-light').select_option('day')
            page.emulate_media(reduced_motion='reduce')
            page.wait_for_function('!chfKitchenEffectsProbe().running')
            page.screenshot(path=str(out/'kitchen-day.png'))
            for key in ('meals','lists','moments','calendar','weather'):
                open_card(key)
                assert not page.evaluate('chfKitchenEffectsProbe().running')
                assert page.locator('.house-life-panel').get_attribute('role')=='region'
                if key=='meals':assert page.evaluate('Alpine.$data(document.getElementById("house-life")).t.type')=='meals_week'
                if key=='calendar':
                    page.wait_for_selector('#kitchen-wall-calendar .fc-daygrid-day')
                    page.locator('#kitchen-wall-calendar .fc-event').first.wait_for()
                    page.locator('#kitchen-wall-calendar .fc-event').first.click()
                    page.wait_for_selector('#simple-event-modal:not(.hidden)')
                    assert 'Family picnic' in page.locator('#modal-title').inner_text()
                    page.keyboard.press('Escape')
                    view('calendar')
                    page.wait_for_selector('#simple-event-modal.hidden',state='attached')
                    assert page.locator('#kitchen-wall-calendar .fc-daygrid-day').count()>=28
                    title=page.locator('.kitchen-calendar-paper h3').inner_text()
                    page.get_by_role('button',name='Next month',exact=True).click()
                    assert page.locator('.kitchen-calendar-paper h3').inner_text()!=title
                    page.get_by_role('button',name='This month',exact=True).click()
                    assert page.locator('.kitchen-calendar-paper h3').inner_text()==title
                if key=='lists':
                    assert page.locator('#kitchen-detail img.is-active').get_attribute('data-kitchen-view')=='pantry'
                    page.get_by_text('Oat milk',exact=True).wait_for()
                    page.get_by_role('button',name='Got Oat milk',exact=True).click()
                    page.get_by_role('button',name='Put Oat milk back',exact=True).wait_for()
                    assert storage.get_shopping_item('kitchen-milk')['is_checked']
                    page.get_by_role('button',name='Put Oat milk back',exact=True).click()
                    page.get_by_role('button',name='Got Oat milk',exact=True).wait_for()
                    assert not storage.get_shopping_item('kitchen-milk')['is_checked']
                if key=='moments':
                    page.wait_for_function('document.querySelectorAll("#kitchen-moment-photos button").length===6')
                    assert page.locator('#kitchen-controls').is_hidden()
                    photo=page.locator('#kitchen-moment-photos button').first
                    photo.focus();page.keyboard.press('Enter')
                    page.get_by_role('button',name='Close photograph').wait_for()
                    assert page.locator('[data-moment-overlay] img').get_attribute('src').endswith('view-0.jpg')
                    page.wait_for_function('Array.from(document.querySelectorAll("#kitchen-moment-photos img")).every(i=>i.complete && i.naturalWidth>0)')
                    page.keyboard.press('Escape')
                    assert page.locator('[data-moment-overlay]').count()==0
                    assert page.evaluate('document.activeElement.closest("#kitchen-moment-photos")!==null')
                    view('moments')
                rect=page.locator('#kitchen-moment-photos button' if key=='moments' else '#kitchen-controls').first.bounding_box()
                assert rect['x']>=0 and rect['y']>=70 and rect['x']+rect['width']<=1401
                page.screenshot(path=str(out/f'{key}-day.png'))
                page.locator('#house-compare-light').select_option('night')
                page.wait_for_function('chfKitchenProbe().light==="night" && document.querySelector("#kitchen-detail img.is-active")?.dataset.light==="night"')
                full_screen()
                page.screenshot(path=str(out/f'{key}-night.png'))
                page.locator('#kitchen-back').click();view('room')
                page.wait_for_function('!history.state?.chfKitchenView')
                page.locator('#house-compare-light').select_option('day')
            open_card('weather')
            for cond,kind in [('rainy','rain'),('snowy','snow'),('fog','fog'),('cloudy','cloudy'),('unavailable','unknown'),('sunny','clear')]:
                payload['window']['cond']=cond
                page.evaluate('(data)=>window.dispatchEvent(new CustomEvent("chf-house-state",{detail:data}))',payload)
                page.wait_for_function('(kind)=>document.getElementById("hybrid-kitchen").dataset.weather===kind',arg=kind)
                if kind!='clear':assert page.locator('[data-outdoors=detail]').evaluate('el=>getComputedStyle(el).backgroundImage!=="none"')
                page.screenshot(path=str(out/f'weather-{kind}.png'))
                if kind in ('rain','snow','fog','cloudy'):
                    page.locator('#house-compare-light').select_option('night')
                    page.wait_for_function('''()=>{
                        const el=document.querySelector('[data-outdoors=detail]');
                        return el.dataset.light==='night' && getComputedStyle(el).visibility==='visible'
                          && document.querySelector('#hybrid-kitchen').dataset.phase==='detail';
                    }''')
                    layer=page.locator('[data-outdoors=detail]')
                    assert layer.evaluate('el=>getComputedStyle(el).filter==="none" && getComputedStyle(el).maskImage==="none"')
                    assert f'kitchen-outside-{kind}-night.png' in layer.evaluate('el=>el.style.backgroundImage')
                    shot=Image.open(io.BytesIO(page.screenshot(path=str(out/f'weather-{kind}-night.png')))).convert('RGB')
                    source=Image.open(Path(__file__).resolve().parents[1]/'static/house_hybrid'/f'kitchen-outside-{kind}-night.png').convert('RGB')
                    plane=page.locator('#kitchen-detail-plane').bounding_box();scale=plane['width']/1536
                    # The clock face and foreground foliage must retain the asset's
                    # indoor exposure, rather than receiving a second night filter.
                    for box in ((950,620,1010,680),(1310,570,1370,610)):
                        screen_box=tuple(round((plane['x'] if i%2==0 else plane['y'])+v*scale) for i,v in enumerate(box))
                        assert 0<=screen_box[0]<screen_box[2]<=shot.width and 0<=screen_box[1]<screen_box[3]<=shot.height
                        rendered=ImageStat.Stat(shot.crop(screen_box)).mean
                        expected=ImageStat.Stat(source.crop(box)).mean
                        assert max(abs(a-b) for a,b in zip(rendered,expected))<15,(kind,box,rendered,expected)
                    page.locator('#house-compare-light').select_option('day')
                    page.wait_for_function('document.querySelector("[data-outdoors=detail]").dataset.light==="day"')
            page.locator('#kitchen-back').click();view('room');page.wait_for_function('!history.state?.chfKitchenView')
            open_card('lists');page.go_back();view('room');page.go_forward();view('lists')
            page.wait_for_function('chfKitchenProbe().phase==="detail"')
            page.keyboard.press('Escape');view('room');page.wait_for_function('!history.state?.chfKitchenView')
            for width,height in ((390,844),(844,390),(2560,1080)):
                page.set_viewport_size({'width':width,'height':height})
                host='#kitchen-shortcuts' if width<701 or height<600 else '#kitchen-hotspots'
                page.locator(host+' [data-card=lists]').click()
                page.wait_for_function('chfKitchenProbe().phase==="detail"')
                full_screen()
                rect=page.locator('#kitchen-controls').bounding_box()
                assert rect['x']>=0 and rect['y']>=0 and rect['x']+rect['width']<=width+1
                assert rect['y']+rect['height']<=height+1
                assert page.locator('#kitchen-back').is_visible()
                page.screenshot(path=str(out/f'lists-{width}.png'))
                page.locator('#kitchen-back').click();view('room');page.wait_for_function('!history.state?.chfKitchenView')
            page.set_viewport_size({'width':1400,'height':1000})
            for key in ('meals','calendar','weather','moments'):
                page.set_viewport_size({'width':390,'height':844})
                page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                open_card(key)
                if key=='calendar':page.wait_for_selector('#kitchen-wall-calendar .fc-daygrid-day')
                if key=='calendar':
                    page.wait_for_function('''()=>{const days=document.querySelectorAll('#kitchen-wall-calendar .fc-daygrid-day');return days[days.length-1].getBoundingClientRect().bottom<=document.querySelector('#kitchen-wall-calendar').getBoundingClientRect().bottom+1;}''')
                if key=='weather':
                    page.wait_for_function('''()=>{const days=document.querySelectorAll('.house-weather-days>div');return days[days.length-1].getBoundingClientRect().bottom<=document.querySelector('#kitchen-controls .house-life-body').getBoundingClientRect().bottom+1;}''')
                page.screenshot(path=str(out/f'{key}-390.png'))
                if key=='moments':
                    # Every print remains reachable even when the phone crops the fridge.
                    photo=page.locator('#kitchen-moment-photos button').last
                    photo.click();page.get_by_role('button',name='Close photograph').click()
                    full_screen()
                for width,height in ((844,390),(1920,1080),(2560,1080)):
                    page.set_viewport_size({'width':width,'height':height})
                    full_screen()
                    if key=='calendar':
                        page.wait_for_function('''()=>Math.abs(document.querySelector('#kitchen-wall-calendar .fc-col-header').getBoundingClientRect().width-document.querySelector('#kitchen-wall-calendar').getBoundingClientRect().width)<4''')
                    if key=='calendar' and width>=1100:
                        box=page.locator('#kitchen-wall-calendar').bounding_box()
                        assert box['width']>=width-310 and box['x']>=0 and box['x']+box['width']<=width+1,box
                        assert box['y']>=0 and box['y']+box['height']<=height-90,box
                        art=page.locator('#kitchen-detail-plane img.is-active')
                        page.wait_for_function("document.querySelector('#kitchen-detail-plane img.is-active').currentSrc.includes('-wide-')")
                        art.evaluate('e=>e.decode()')
                        frame=page.locator('#kitchen-detail-plane .house-paper-frame').bounding_box()
                        assert frame['x']==20 and frame['width']==width-40,frame
                        assert frame['y']==76 and frame['height']==height-172,frame
                        assert box['height']>=height-440,box
                        page.locator('#kitchen-detail-plane .house-paper-frame img').evaluate_all('els=>Promise.all(els.map(e=>e.decode()))')
                        cells=page.locator('#kitchen-wall-calendar .fc-daygrid-day')
                        assert cells.first.bounding_box()['width']>175
                        assert cells.last.bounding_box()['y']+cells.last.bounding_box()['height']<=box['y']+box['height']+1
                    page.screenshot(path=str(out/f'{key}-{width}.png'))
                page.locator('#kitchen-back').click();view('room');page.wait_for_function('!history.state?.chfKitchenView')
            page.set_viewport_size({'width':1400,'height':1000})
            page.locator('#hybrid-outside').click();mode('exterior')
            page.go_forward();mode('kitchen')
            page.goto(served.url('house?compare=exterior&scene=kitchen&light=night'));mode('kitchen')
            page.wait_for_function('chfKitchenProbe().light==="night"')
            page.screenshot(path=str(out/'kitchen-night.png'))
            page.goto(served.url('house?compare=exterior&scene=kitchen&panel=true&light=night'));mode('kitchen')
            page.set_viewport_size({'width':1920,'height':1080})
            for i in range(3):
                open_card('calendar')
                page.wait_for_selector('#kitchen-wall-calendar .fc-daygrid-day')
                art=page.locator('#kitchen-detail-plane img.is-active');art.evaluate('e=>e.decode()')
                assert '-wide-night.png' in art.evaluate('e=>e.currentSrc')
                assert page.locator('#kitchen-controls .house-life-panel').evaluate("e=>getComputedStyle(e).backgroundColor==='rgba(0, 0, 0, 0)'")
                if i==0:page.screenshot(path=str(out/'calendar-panel-night.png'))
                page.locator('#kitchen-back').click();view('room');page.wait_for_function('!history.state?.chfKitchenView')
            assert page.evaluate('typeof THREE')=='undefined'
            assert not served.errors(),served.errors()
            print('PASS: kitchen cards, day/night, paper registration, mobile, history, direct entry and no WebGL')
    finally:served.stop()


if __name__=='__main__':main()
