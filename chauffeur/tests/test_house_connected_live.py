"""Connected hybrid rooms, complete icons, full-screen objects and private Study."""
import argparse
from pathlib import Path
from test_house_hybrid_live import seed as base_seed, live_app, ha_api, storage
import connected_rooms_demo as demo
import main as app_main


def seed():
    base_seed()
    demo.seed()
    demo.install()
    app_main._notify_challenge=lambda *args,**kwargs:False
    app_main._notify_challenge_answered=lambda *args,**kwargs:False


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True)
    out=Path(p.parse_args().out).resolve();out.mkdir(parents=True,exist_ok=True)
    ha_api.get_states=lambda *a,**kw:[];ha_api.get_state=lambda *a,**kw:None
    served=live_app(seed)
    try:
        with served.browser(reduced_motion='reduce',has_touch=True) as page:
            page.set_default_timeout(20000)
            page.route('**/api/v2/chat/stream*',lambda r:r.fulfill(status=204,body=''))
            private_requests=[]
            page.on('request',lambda r:private_requests.append(r) if '/api/study/state' in r.url else None)
            def mode(name):page.wait_for_function('(name)=>chfHouseMode()===name',arg=name)
            def walk(name):page.locator(f'#hybrid-walkthrough [data-room={name}]').click();mode(name)
            def open_object(room,key):
                page.locator(f'#hybrid-{room} :is(.utility-shortcuts,.utility-hotspots) [data-card={key}]:visible').click()
                page.wait_for_selector(f'#hybrid-{room}[data-phase=detail]')
                if room=='mudroom':page.wait_for_function('!Alpine.$data(document.getElementById("house-life")).loading')
            def close_object(room):
                page.locator(f'#hybrid-{room} .utility-back').click()
                page.wait_for_function('!history.state?.chfUtilityView')
            def cover(room):
                assert page.locator(f'#hybrid-{room} .utility-plane img.is-active').evaluate('''el=>{const r=el.getBoundingClientRect();return r.left<=1&&r.top<=1&&r.right>=innerWidth-1&&r.bottom>=innerHeight-1&&Math.abs(r.width/r.height-1.5)<.001;}''')
                assert page.locator('#hybrid-walkthrough').is_hidden()
            page.goto(served.url('house?compare=exterior&light=day'))
            page.wait_for_function('window.chfExteriorProbe?.().ready')
            page.locator('#exterior-kitchen-enter').click()
            for key in ('moments','meals','lists','calendar','weather'):
                assert page.locator(f'.house-marker-feature[data-preview={key}] .house-marker-face>svg:not(.house-hold-ring)').count()==1
            assert page.locator('.house-marker-feature[data-preview=lists] .house-feature-label').inner_text()=='Groceries'
            page.screenshot(path=str(out/'kitchen-icons.png'))
            page.locator('#exterior-kitchen-marker').click();mode('kitchen')
            assert page.locator('#kitchen-hotspots [data-card=lists]').get_attribute('aria-label')=='Groceries'
            walk('mudroom');page.screenshot(path=str(out/'mudroom-day.png'))
            for key,text in [('schedule',None),('chores','Water the hallway plants'),('routines','Pack school bag')]:
                open_object('mudroom',key);cover('mudroom')
                if text:page.get_by_text(text,exact=True).first.wait_for()
                page.screenshot(path=str(out/f'mudroom-{key}-day.png'))
                page.locator('#house-compare-light').select_option('night')
                page.wait_for_selector('#hybrid-mudroom .utility-plane img.is-active[data-light=night]')
                cover('mudroom');page.screenshot(path=str(out/f'mudroom-{key}-night.png'))
                close_object('mudroom');page.locator('#house-compare-light').select_option('day')
            walk('garage');walk('mudroom');walk('kitchen');walk('living')
            page.go_back();mode('kitchen');page.go_back();mode('mudroom');page.go_forward();mode('kitchen');page.go_forward();mode('living')
            assert not private_requests
            page.locator('#hybrid-walkthrough [data-room=study]').click()
            page.wait_for_selector('#cc-input-field:visible');page.fill('#cc-input-field','1234');page.click('#cc-input-ok-btn');mode('study')
            token=page.evaluate('chfHouseParent().token')
            assert storage.get_member_by_token(token)['id']=='room-demo-parent'
            assert private_requests and all(r.headers.get('x-member-token')==token for r in private_requests)
            page.screenshot(path=str(out/'study-day.png'))
            keys=['board','desk','tray','stickies','calendar','window','contracts','binders','gauges','monitor','map']
            for key in keys:
                open_object('study',key);cover('study')
                assert page.locator('#study-controls').inner_text().strip()
                if key=='gauges':assert page.locator('.study-dial').count()==2
                if key=='map':assert page.locator('.study-map-pin').count()==3
                if key=='calendar':assert page.locator('.study-calendar article').count()==42
                page.screenshot(path=str(out/f'study-{key}-day.png'))
                page.locator('#house-compare-light').select_option('night')
                page.wait_for_selector('#hybrid-study .utility-plane img.is-active[data-light=night]')
                cover('study');page.screenshot(path=str(out/f'study-{key}-night.png'))
                close_object('study');page.locator('#house-compare-light').select_option('day')
            for w,h in ((390,844),(844,390),(2560,1080)):
                page.set_viewport_size({'width':w,'height':h})
                for key in ('board','desk','calendar','binders','monitor'):
                    open_object('study',key);cover('study')
                    assert page.locator('#study-controls .study-paper').is_visible()
                    page.screenshot(path=str(out/f'study-{key}-{w}.png'));close_object('study')
            page.set_viewport_size({'width':1400,'height':1000})
            page.locator('#study-lock').click();mode('living')
            page.wait_for_function('!chfHouseParent() && !chfUtilityProbe().privateLoaded')
            assert not page.locator('#study-controls').inner_text()
            page.go_back();page.wait_for_selector('#cc-input-field:visible')
            assert not page.locator('#hybrid-study').is_visible()
            page.keyboard.press('Escape')
            # A returning parent must authenticate again; expiry removes the data.
            page.locator('#hybrid-walkthrough [data-room=study]').click()
            page.wait_for_selector('#cc-input-field:visible');page.fill('#cc-input-field','1234');page.click('#cc-input-ok-btn');mode('study')
            open_object('study','board')
            page.evaluate('''()=>{const s=JSON.parse(sessionStorage.getItem('chauffeur_house_parent'));s.expires=Date.now()-1;sessionStorage.setItem('chauffeur_house_parent',JSON.stringify(s));}''')
            mode('living')
            assert not page.locator('#study-controls').inner_text()
            assert not page.evaluate('chfUtilityProbe().privateLoaded')
            page.goto(served.url('house?compare=exterior&scene=mudroom&light=night'));mode('mudroom')
            for w,h in ((390,844),(844,390),(2560,1080)):
                page.set_viewport_size({'width':w,'height':h})
                for key in ('schedule','chores','routines'):
                    open_object('mudroom',key);cover('mudroom');page.screenshot(path=str(out/f'mudroom-{key}-{w}.png'));close_object('mudroom')
            assert page.evaluate('typeof THREE')=='undefined'
            assert not served.errors(),served.errors()
            print('PASS: five connected rooms; kitchen icons/Groceries; 14 object views day/night; responsive full-screen; PIN/lock/history')
    finally:served.stop()


if __name__=='__main__':main()
