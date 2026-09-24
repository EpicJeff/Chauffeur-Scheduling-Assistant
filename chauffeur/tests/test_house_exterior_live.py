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
            assert page.locator('.exterior-vehicle').count() == 1  # Cars now live inside the garage.
            assert page.locator('[data-vehicle="away"]').count() == 0
            assert '3 home' in page.locator('#exterior-cars-shortcut').inner_text()
            page.locator('#exterior-cars-shortcut').click()
            page.wait_for_selector('.house-life-panel:visible')
            mode('exterior')
            page.get_by_role('button', name='Close and return to house', exact=True).click()
            page.locator('#exterior-bus-shortcut').click()
            page.wait_for_selector('.house-life-panel:visible')
            mode('exterior')
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
            for key in ('music', 'pets', 'tasks', 'programs'):
                page.locator(f'#hybrid-hotspots [data-card="{key}"]').click()
                page.wait_for_selector(f'#hybrid-room-frame[data-view="{key}"][data-phase="detail"]')
                assert page.locator('#hybrid-outside').is_hidden()
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
            (out/'results.json').write_text(json.dumps({'passed':True,'views':1,'webglAttempts':0}, indent=2))
            print('PASS: single exterior, shared previews and hold visits, history, touch and live traffic')
    except Exception:
        print('BROWSER ERRORS', served.errors(), flush=True)
        raise
    finally:
        served.stop()


if __name__ == '__main__':
    main()
