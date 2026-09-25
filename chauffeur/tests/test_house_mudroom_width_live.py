"""Wide mudroom paper uses the panel width without stretching the photograph."""
from pathlib import Path
from test_house_hybrid_live import seed as base_seed, live_app, ha_api, storage
from models.schemas import Chore, RoutineItem


def seed():
    base_seed()
    storage.patch_settings({'house_hybrid_enabled': True, 'panel_idle_return_seconds': 0})
    for i in range(3, 6):
        storage.add_member({'id': 'k'+str(i), 'name': 'Child '+str(i), 'role': 'child'})
    for i in range(1, 6):
        member='k'+str(i)
        storage.add_chore(Chore(title='Tidy '+str(i),owner=member,state='claimed',claimed_by=member).model_dump())
        storage.add_routine(RoutineItem(member_id=member,title='Get ready '+str(i),time_of_day='07:00').model_dump())


def main():
    ha_api.get_states=lambda *a,**k:[]
    ha_api.get_state=lambda *a,**k:None
    served=live_app(seed)
    out=Path('../scratch/mudroom-width');out.mkdir(parents=True,exist_ok=True)
    try:
        with served.browser(reduced_motion='reduce') as page:
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=204,body=''))
            page.goto(served.url('house?panel=true&scene=mudroom&light=day'))
            page.wait_for_function("window.chfHouseMode?.()==='mudroom'")
            for key in ('chores','routines'):
                page.set_viewport_size({'width':2560,'height':1440})
                page.locator('#hybrid-mudroom .utility-hotspots [data-card='+key+']').click()
                grid=page.locator('.house-life-lanes > .grid')
                page.wait_for_function('document.querySelectorAll(".house-life-lanes > .grid > div").length===5')
                for w,h in ((2560,1440),(1920,1080),(1400,900),(390,844),(844,390)):
                    page.set_viewport_size({'width':w,'height':h})
                    page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                    box=page.locator('#hybrid-mudroom .house-life-panel').bounding_box()
                    assert box['x']>=0 and box['x']+box['width']<=w+1,box
                    assert box['y']>=0 and box['y']+box['height']<=h+1,box
                    if w>=1100:
                        assert box['width']>=w*.74,box
                    columns=grid.evaluate('e=>getComputedStyle(e).gridTemplateColumns.split(" ").filter(v=>parseFloat(v)>0).length')
                    if w>=1920:
                        assert columns==5, (key,w,columns)
                        rows=grid.locator(':scope > div').evaluate_all('els=>els.map(e=>e.getBoundingClientRect().top)')
                        assert max(rows)-min(rows)<1,rows
                    if w==390:assert columns==1
                    image=page.locator('#hybrid-mudroom .utility-plane img.is-active').bounding_box()
                    assert abs(image['width']/image['height']-1.5)<.001
                    art=page.locator('#hybrid-mudroom .utility-plane img.is-active')
                    page.wait_for_function("([selector,wide])=>document.querySelector(selector).currentSrc.includes('-wide-')===wide",arg=['#hybrid-mudroom .utility-plane img.is-active',w>=1100])
                    if w>=1100:
                        # All four physical edges and the brass clip remain in view.
                        frame=(244,147,1115,400) if key=='chores' else (282,342,974,430)
                        scale=image['width']/1536
                        x=image['x']+frame[0]*scale;y=image['y']+frame[1]*scale
                        assert x>=16 and x+frame[2]*scale<=w-16,(key,w,x)
                        assert y>=65 and y+frame[3]*scale<=h-80,(key,w,y)
                        assert art.evaluate('e=>e.complete && e.naturalWidth===1536')
                    assert page.locator('#hybrid-mudroom .house-life-panel').evaluate("e=>getComputedStyle(e).backgroundColor==='rgba(0, 0, 0, 0)'")
                    page.screenshot(path=str(out/(key+'-'+str(w)+'.png')))
                    if w==1920:
                        page.evaluate("dispatchEvent(new CustomEvent('chf-house-light',{detail:true}))")
                        page.wait_for_function("document.querySelector('#hybrid-mudroom .utility-plane img.is-active').dataset.light==='night'")
                        art=page.locator('#hybrid-mudroom .utility-plane img.is-active')
                        art.evaluate('e=>e.decode()')
                        assert '-wide-night.png' in art.evaluate('e=>e.currentSrc')
                        page.screenshot(path=str(out/(key+'-night.png')))
                        page.evaluate("dispatchEvent(new CustomEvent('chf-house-light',{detail:false}))")
                        page.wait_for_function("document.querySelector('#hybrid-mudroom .utility-plane img.is-active').dataset.light==='day'")
                page.locator('#hybrid-mudroom .utility-back').click()
                page.wait_for_function('!history.state?.chfUtilityView')
            assert not served.errors(),served.errors()
            print('PASS wide chores/routines: five lanes, responsive width, phone layouts and undistorted artwork')
    finally:served.stop()


if __name__=='__main__':main()
