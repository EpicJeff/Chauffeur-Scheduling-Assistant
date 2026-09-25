"""Single exterior, shared markers, live vehicles and hybrid rooms without WebGL."""
import argparse
import json
from pathlib import Path
from test_house_hybrid_live import seed, live_app, ha_api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    assert served, 'Playwright required'
    try:
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            page.set_default_timeout(20000)
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
            page.route('**/api/music/favorites*', lambda r: r.fulfill(
                status=200, content_type='application/json', body='{"items":[]}'))
            bus_rows=[{'member_id':'bus:42','name':"Maya & Finn's bus 42",'is_car':True,'avatar':'Bus','state':'near_stop','latitude':35.8,'longitude':-78.6},
                      {'member_id':'stop:home','name':"Maya & Finn's stop",'is_car':True,'state':None,'latitude':35.801,'longitude':-78.601}]
            def bus_map(route):
                from urllib.parse import urlparse,parse_qs
                raw=parse_qs(urlparse(route.request.url).query).get('widgets',[''])[0]
                if raw.startswith('['):
                    widgets=json.loads(raw)
                    assert widgets[0]['config']=={'people':False,'cars':False,'buses':True,'interactive':True}
                    route.fulfill(json={'tiles':[{'type':'map','data':{'people':bus_rows,'center':None}}]})
                else:route.fallback()
            page.route('**/api/home_board?widgets=*',bus_map)
            fleet = [
                {'id':'suv','name':'White 2022 Mercedes GLS','body':'suv','color':'#ffffff','present':True,'battery_pct':14,'warn':True,
                 'exterior_image':'static/house_hybrid/vehicles/mercedes-gls-2022-white.png'},
                {'id':'van','name':'Gray 2026 Kia EV9','body':'suv','present':True,'battery_pct':65,'warn':False,
                 'exterior_image':'static/house_hybrid/vehicles/kia-ev9-2026-gray.png'},
                {'id':'murano','name':'Blue 2021 Nissan Murano','body':'suv','present':True,'fuel_pct':65,'warn':False,
                 'exterior_image':'static/house_hybrid/vehicles/nissan-murano-2021-blue.png'},
                {'id':'away','name':'Away car','body':'sedan','present':False,'warn':False}]
            payload = {'garage':{'cars':fleet}, 'curb':{'bus':True}, 'window':{'night':False}}
            page.route('**/api/house/state*', lambda r:r.fulfill(status=200, content_type='application/json', body=json.dumps(payload)))
            page.add_init_script('''window.webglAttempts=0;
                const context=HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext=function(kind,...args){
                    if (/webgl/.test(kind)) { window.webglAttempts++; return null; }
                    return context.call(this,kind,...args);
                };''')
            def mode(value):
                page.wait_for_function('(m)=>window.chfExteriorProbe?.().mode===m', arg=value)
            def ready():
                page.wait_for_function('window.chfExteriorProbe?.().ready')
            page.goto(served.url('house?compare=exterior&light=day'))
            ready()
            assert page.locator('#hybrid-room').evaluate('el=>el.inert')
            assert page.evaluate('typeof THREE') == 'undefined'
            assert page.evaluate('webglAttempts') == 0
            assert page.locator('#exterior-pictures').bounding_box() == {'x':0,'y':0,'width':1400,'height':1000}
            assert page.locator('#exterior-pictures > img').count() == 1
            assert page.locator('.exterior-orbit').count() == 0
            page.wait_for_selector('[data-vehicle="school-bus"]')
            assert page.locator('#exterior-fleet').count()==0
            assert page.locator('.exterior-garage-car').count()==2
            assert '14% charge' in page.locator('.exterior-garage-car[data-vehicle=suv]').get_attribute('aria-label')
            assert page.locator('.exterior-garage-car[data-vehicle=van]').get_attribute('data-bay')=='left'
            assert page.locator('.exterior-garage-car[data-vehicle=suv]').get_attribute('data-bay')=='right'
            assert page.locator('[data-vehicle="school-bus"]').evaluate('n=>n.style.width')=='37%'
            page.locator('#exterior-layer-controls summary').click()
            page.locator('#exterior-driveway-preview').select_option('home')
            page.wait_for_selector('[data-vehicle="driveway-car"]')
            page.wait_for_function("Array.from(document.querySelectorAll('.exterior-scene-patch')).every(i=>i.complete && i.naturalWidth)")
            # Body and tires stay opaque, shadow feathers, surrounding pavement is absent.
            assert page.locator('.exterior-scene-patch').evaluate('''async i=>{
                const css=getComputedStyle(i), mask=new Image();
                mask.src=css.maskImage.slice(5,-2);await mask.decode();
                const c=document.createElement('canvas');c.width=1536;c.height=1024;
                const x=c.getContext('2d');x.drawImage(mask,0,0);
                const alpha=(px,py)=>x.getImageData(px,py,1,1).data[3];
                return css.clipPath==='none' && alpha(820,800)>250 && alpha(855,860)>250
                    && alpha(780,875)>0 && alpha(780,875)<240
                    && alpha(700,900)===0 && alpha(1050,680)===0;
            }'''), 'vehicle mask must preserve the body and feather only the contact shadow'
            assert page.locator('.exterior-garage-layer').evaluate('''async el=>{
                const css=getComputedStyle(el), mask=new Image();
                mask.src=css.maskImage.slice(5,-2);await mask.decode();
                const c=document.createElement('canvas');c.width=1536;c.height=1024;
                const x=c.getContext('2d');x.drawImage(mask,0,0);
                const alpha=(px,py)=>x.getImageData(px,py,1,1).data[3];
                return css.clipPath==='none' && alpha(1000,690)>250
                    && alpha(1000,765)>0 && alpha(1000,765)<240 && alpha(910,680)===0;
            }'''), 'garage floor must blend without replacing the door jamb'
            page.screenshot(path=str(out/'vehicles-composite.png'))
            # The patch must retain the photograph's exact cover projection,
            # including its bottom alignment at narrow and ultrawide sizes.
            for width, height in ((390,844),(2560,1080),(1400,1000)):
                page.set_viewport_size({'width':width,'height':height})
                page.wait_for_function('''() => {
                    const base=document.getElementById('exterior-photo');
                    const patch=document.querySelector('.exterior-scene-patch');
                    const plane=document.getElementById('exterior-traffic').getBoundingClientRect();
                    const r=patch.getBoundingClientRect();
                    const s=Math.max(innerWidth/base.naturalWidth,innerHeight/base.naturalHeight);
                    return patch.naturalWidth===base.naturalWidth && patch.naturalHeight===base.naturalHeight
                        && Math.abs(plane.width-base.naturalWidth*s)<1
                        && Math.abs(plane.height-base.naturalHeight*s)<1
                        && Math.abs(plane.x-(innerWidth-plane.width)*(innerWidth<701?.8:.5))<1
                        && Math.abs(plane.bottom-innerHeight)<1
                        && Math.abs(r.width-plane.width)<1
                        && Math.abs(r.height-plane.height)<1
                        && Math.abs(r.x-plane.x)<1
                        && Math.abs(r.y-plane.y)<1;
                }''')
                page.screenshot(path=str(out/f'vehicles-{width}.png'))
                if width==390:
                    assert page.locator('.exterior-garage-car').evaluate_all('els=>els.every(e=>{const r=e.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth&&r.width>=44&&r.height>=44})')
            # Independent live presence in both spaces of ONE double garage,
            # plus the driveway, including unknown presence (never assumed home).
            page.locator('#exterior-driveway-preview').select_option('live')
            for left,right,driveway in ((l,r,d) for l,r in ((True,False),(False,True),(False,False),(True,True)) for d in (False,True)):
                fleet[1]['present']=left;fleet[0]['present']=right;fleet[2]['present']=driveway
                page.evaluate('async()=>{await chfHouseRefresh()}')
                assert page.locator('.exterior-garage-car[data-bay=left]').count()==int(left)
                assert page.locator('.exterior-garage-car[data-bay=right]').count()==int(right)
                state='both' if left and right else 'left' if left else 'right' if right else 'empty'
                assert page.locator('#exterior-traffic').get_attribute('data-garage-state')==state
                assert page.locator('.exterior-garage-layer').count()==int(left or right)
                assert page.locator('[data-vehicle=driveway-car]').count()==int(driveway)
                assert page.locator('.exterior-driveway-shadow').count()==int(driveway)
                page.wait_for_function("Array.from(document.querySelectorAll('#exterior-traffic img')).every(i=>i.complete && i.naturalWidth)")
                assert page.locator('.exterior-garage-layer img').evaluate_all("els=>els.every(i=>getComputedStyle(i).transform==='none')")
                page.screenshot(path=str(out/f'garage-{left}-{right}-{driveway}.png'))
            fleet[1]['present']=None
            page.evaluate('async()=>{await chfHouseRefresh()}')
            assert page.locator('.exterior-garage-car[data-bay=left]').count()==0
            fleet[1]['present']=True
            page.evaluate('async()=>{await chfHouseRefresh()}')
            page.locator('.exterior-garage-car[data-vehicle=suv]').hover()
            page.screenshot(path=str(out/'garage-hover.png'))
            page.locator('.exterior-garage-car[data-vehicle=suv]').click()
            page.wait_for_selector('#garage-dashboard:visible')
            assert page.locator('#garage-dashboard').get_attribute('data-vehicle') == 'suv'
            page.locator('#garage-dashboard-back').click(); mode('exterior')
            page.locator('[data-vehicle="driveway-car"]').click()
            page.wait_for_selector('#garage-dashboard:visible')
            assert page.locator('#garage-dashboard').get_attribute('data-vehicle') == 'murano'
            page.locator('#garage-dashboard-back').click(); mode('exterior')
            page.locator('#exterior-driveway-preview').select_option('away')
            assert page.locator('[data-vehicle="driveway-car"]').count() == 0
            page.locator('#exterior-bus-preview').select_option('away')
            assert page.locator('[data-vehicle="school-bus"]').count() == 0
            page.locator('#exterior-bus-preview').select_option('live')
            page.locator('#exterior-layer-controls summary').click()

            assert page.locator('.exterior-vehicle').count() == 1  # Bus baseline retained; driveway preview explicitly empty.
            assert page.locator('[data-vehicle="away"]').count() == 0
            assert '3 home' in page.locator('#exterior-cars-shortcut').inner_text()
            page.locator('#exterior-cars-shortcut').click()
            page.wait_for_selector('.house-life-panel:visible')
            mode('exterior')
            page.get_by_role('button', name='Close and return to house', exact=True).click()
            def exterior_geometry():
                return page.evaluate("['house-exterior','exterior-pictures','exterior-photo','exterior-traffic'].map(id=>{let e=document.getElementById(id);return [id,e.scrollLeft,e.scrollTop,e.getBoundingClientRect().toJSON()];})")
            before=exterior_geometry()
            for target in ('#exterior-bus-shortcut','[data-vehicle="school-bus"]'):
                page.locator(target).evaluate('e=>e.focus({preventScroll:true})')
                page.keyboard.press('Enter')
                page.wait_for_selector('#house-bus-map .leaflet-marker-icon')
                assert page.locator('#house-life-title').inner_text()=='School buses'
                assert page.locator('#house-bus-map .leaflet-marker-icon').count()==2
                assert "Maya & Finn's bus 42" in page.locator('.house-life-panel').inner_text()
                mode('exterior')
                page.screenshot(path=str(out/'bus-map.png'))
                page.get_by_role('button', name='Close and return to house', exact=True).click()
                assert exterior_geometry()==before,'Closing a bus must not scroll or resize the house'
                assert page.locator('#house-bus-map .leaflet-pane').count()==0
            bus_rows.clear()
            page.locator('#exterior-bus-shortcut').click()
            page.get_by_text('No bus location is available right now.',exact=False).wait_for()
            page.get_by_role('button', name='Close and return to house', exact=True).click()
            page.evaluate('async () => { await chfHouseRefresh(); }')
            payload['curb']['bus'] = False
            fleet[0]['present'] = False
            page.evaluate('async () => { await chfHouseRefresh(); }')
            page.wait_for_function("!document.querySelector('[data-vehicle=\"school-bus\"]') && !document.querySelector('[data-vehicle=\"suv\"]')")
            payload['curb']['bus'] = True
            fleet[0]['present'] = True
            page.evaluate('async () => { await chfHouseRefresh(); }')
            page.wait_for_selector('[data-vehicle="school-bus"]')
            page.screenshot(path=str(out/'exterior-desktop.png'))
            page.evaluate('window.documentToken="same-document"')
            page.locator('#exterior-room-marker').click()
            assert page.locator('#exterior-room-marker').get_attribute('aria-expanded') == 'true'
            for key in ('music', 'pets', 'tasks', 'programs'):
                page.locator(f'.house-marker-feature[data-preview="{key}"]').click()
                page.wait_for_selector('.house-life-panel:visible')
                page.wait_for_function("!Alpine.$data(document.getElementById('house-life')).loading")
                mode('exterior')
                assert page.locator('.house-life-panel').get_attribute('role') == 'dialog'
                assert not page.locator('#house-book').is_visible()
                assert not page.locator('#house-habitat').is_visible()
                page.get_by_role('button', name='Close and return to house', exact=True).click()
                assert page.locator('#exterior-room-marker').get_attribute('aria-expanded') == 'true'
            page.screenshot(path=str(out/'exterior-expanded.png'))
            page.locator('#exterior-room-marker').click()
            mode('living')
            assert 'scene=living' in page.url
            assert page.locator('#house-exterior').is_hidden()
            assert not page.locator('#hybrid-room').evaluate('el=>el.inert')
            page.screenshot(path=str(out/'living-desktop.png'))
            assert not page.evaluate('chfEffectsProbe().running')  # Reduced motion.
            page.emulate_media(reduced_motion='no-preference')
            try:
                page.wait_for_function('chfEffectsProbe().frames > 3')
            except Exception:
                print('EFFECT STATE', page.evaluate('''() => ({probe:chfEffectsProbe(),
                    scene:document.body.dataset.houseScene,frame:{...document.getElementById('hybrid-room-frame').dataset},
                    hidden:document.hidden,checked:document.getElementById('hybrid-effects-toggle').checked,
                    images:['hybrid-day','hybrid-night'].map(id=>{const i=document.getElementById(id);return [id,i.complete,i.naturalWidth]})})'''))
                raise
            page.locator('#hybrid-effects-toggle').uncheck()
            assert not page.evaluate('chfEffectsProbe().running')
            page.locator('#hybrid-effects-toggle').check()
            page.wait_for_function('chfEffectsProbe().running')
            page.emulate_media(reduced_motion='reduce')

            for key in ('music', 'pets', 'tasks', 'programs'):
                page.locator(f'#hybrid-hotspots [data-card="{key}"]').click()
                page.wait_for_selector(f'#hybrid-room-frame[data-view="{key}"][data-phase="detail"]')
                assert page.locator('#hybrid-outside').is_hidden()
                assert not page.evaluate('chfEffectsProbe().running')
                page.keyboard.press('Escape')
                page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
                mode('living')
            page.keyboard.press('Escape')
            mode('exterior')
            ready()
            page.go_forward()
            mode('living')
            page.locator('#hybrid-outside').click()
            mode('exterior')
            assert page.evaluate('documentToken') == 'same-document'
            # Deep links/reloads preserve both scene and exterior angle.
            page.goto(served.url('house?compare=exterior&light=day&angle=6&scene=living'))
            mode('living')
            ready()
            page.reload()
            mode('living')
            assert 'scene=living' in page.url
            page.locator('#hybrid-outside').click()
            mode('exterior')
            ready()
            page.set_viewport_size({'width':390,'height':844})
            assert page.locator('#exterior-enter').is_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(out/'exterior-phone.png'))
            page.locator('#exterior-enter').tap()
            page.screenshot(path=str(out/'exterior-expanded-phone.png'))
            buttons = page.locator('.house-marker-feature')
            assert buttons.count() == 4
            for box in buttons.evaluate_all('(els)=>els.map(el=>{const r=el.getBoundingClientRect();return [r.left,r.top,r.right,r.bottom]})'):
                assert 0 <= box[0] < box[2] <= 390 and 0 <= box[1] < box[3] <= 844, box
            button = page.locator('.house-marker-feature[data-preview="music"]')
            box = button.bounding_box()
            x, y = box['x'] + box['width']/2, box['y'] + 25
            page.mouse.move(x,y)
            page.mouse.down()
            page.mouse.move(x+35,y)
            page.mouse.up()
            mode('exterior')
            assert not page.locator('.house-life-panel').is_visible()
            page.mouse.move(x,y)
            page.mouse.down()
            page.wait_for_timeout(650)
            page.mouse.up()
            mode('living')
            page.wait_for_selector('#hybrid-room-frame[data-view="music"][data-phase="detail"]')
            page.locator('#hybrid-view-back').tap()
            page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            page.locator('#hybrid-outside').tap()
            mode('exterior')
            # The keyboard alternative uses the same controller and destination.
            page.locator('#exterior-enter').tap()
            page.locator('.house-marker-feature[data-preview="tasks"]').focus()
            page.keyboard.press('Shift+Enter')
            page.wait_for_selector('#hybrid-room-frame[data-view="tasks"][data-phase="detail"]')
            page.locator('#hybrid-view-back').tap()
            page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            page.locator('#hybrid-outside').tap()
            mode('exterior')
            assert page.evaluate('webglAttempts') == 0
            assert not served.errors(), served.errors()
            # Exercise the actual transition as well as reduced motion.
            page.emulate_media(reduced_motion='no-preference')
            page.locator('#exterior-enter').tap()
            page.locator('#exterior-room-marker').tap()
            mode('entering')
            mode('living')
            assert not [e for e in served.errors() if 'net::ERR_FAILED' not in e], served.errors()
            page.wait_for_function('chfEffectsProbe().running')
            page.locator('#house-compare-light').select_option('night')
            page.wait_for_selector('#hybrid-room-frame[data-light="night"]')
            page.screenshot(path=str(out/'fireplace-night.png'))
            page.locator('#hybrid-shortcuts [data-card="music"]').click()
            page.wait_for_selector('#hybrid-room-frame[data-phase="detail"]')
            assert not page.evaluate('chfEffectsProbe().running')
            page.goto(served.url('house?compare=exterior&light=day&driveway_car=murano'))
            ready()
            page.wait_for_selector('[data-vehicle="driveway-car"]')
            fleet[2]['present'] = False
            page.evaluate('async()=>await chfHouseRefresh()')
            page.wait_for_function('!document.querySelector("[data-vehicle=driveway-car]")')
            page.wait_for_function("document.querySelector('#exterior-cars-shortcut')?.textContent.includes('2 home')")
            assert page.locator('.exterior-garage-car').count()==2
            assert not page.evaluate('chfEffectsProbe().running')
            (out/'results.json').write_text(json.dumps({'passed':True,'views':1,'webglAttempts':0}, indent=2))
            print('PASS: single exterior, shared previews and hold visits, history, touch and live traffic')
    except Exception:
        print('BROWSER ERRORS', served.errors(), flush=True)
        raise
    finally:
        served.stop()


if __name__ == '__main__':
    main()
