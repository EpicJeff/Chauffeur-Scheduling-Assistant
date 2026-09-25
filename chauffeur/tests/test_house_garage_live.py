"""One scene-matched garage bay: navigation, live presence and local preview."""
import argparse
import json
from pathlib import Path
from test_house_hybrid_live import seed, live_app, ha_api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    out = Path(parser.parse_args().out); out.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    try:
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            page.route('**/api/v2/chat/stream*', lambda r:r.fulfill(status=204, body=''))
            payload = {'garage':{'cars':[{'id':'ev9','name':'Gray 2026 Kia EV9','present':True,'battery_pct':63,'range':218,'range_unit':'mi'}]}, 'curb':{'bus':False}}
            page.route('**/api/house/state*', lambda r:r.fulfill(status=200, content_type='application/json', body=json.dumps(payload)))
            writes = []
            page.on('request', lambda r: writes.append(r.url) if r.method in ('PUT','POST','DELETE','PATCH') and '/api/' in r.url else None)
            def mode(value):
                page.wait_for_function('(m)=>chfExteriorProbe().mode===m', arg=value)
            def occupied(value):
                page.wait_for_function('(v)=>document.getElementById("hybrid-garage").dataset.occupied===String(v)', arg=value)
            page.goto(served.url('house?compare=exterior&light=day&garage_car=ev9'))
            page.wait_for_function('window.chfExteriorProbe?.().ready')
            page.locator('#exterior-garage-marker').click()
            page.locator('[data-preview="cars"]').click()
            page.wait_for_selector('.house-life-panel:visible')
            mode('exterior')
            page.get_by_role('button', name='Close and return to house', exact=True).click()
            page.locator('#exterior-garage-marker').click()
            mode('garage'); occupied(True)
            assert page.locator('#hybrid-room').evaluate('e=>e.inert')
            assert 'scene=garage' in page.url
            assert '63% battery' in page.locator('#garage-state').inner_text()
            page.screenshot(path=str(out/'garage-parked.png'))
            page.locator('#garage-car').click()
            page.wait_for_selector('#garage-dashboard:visible')
            assert page.locator('#cluster-energy').inner_text() == '63%'
            assert page.locator('#cluster-range').inner_text() == '218'
            assert page.locator('#cluster-range-unit').inner_text() == 'mi'
            page.screenshot(path=str(out/'garage-dashboard.png'))
            payload['garage']['cars'][0].update(battery_pct=17, warn=True, range=221, range_unit='km')
            page.evaluate('async()=>{await chfHouseRefresh()}')
            page.wait_for_function("document.getElementById('cluster-energy').textContent === '17%'")
            assert page.locator('#cluster-range-unit').inner_text() == 'km'
            assert page.locator('#garage-cluster-ui').get_attribute('data-warn') == 'true'
            payload['garage']['cars'][0].update(battery_pct=None, range=None)
            page.evaluate('async()=>{await chfHouseRefresh()}')
            page.wait_for_function("document.getElementById('cluster-energy').textContent === '—'")
            assert page.locator('#cluster-range').inner_text() == '—'
            payload['garage']['cars'][0].update(battery_pct=63, range=218, range_unit='mi', warn=False)
            page.evaluate('async()=>{await chfHouseRefresh()}')
            page.locator('#cluster-more').click()
            page.wait_for_selector('.house-life-panel:visible')
            assert page.locator('.house-life-panel').get_attribute('role') == 'dialog'
            page.get_by_role('button', name='Close and return to house', exact=True).click()
            mode('garage')
            page.locator('#garage-dashboard-back').click()
            page.locator('#garage-presence').select_option('away'); occupied(False)
            assert page.locator('#garage-car').is_hidden()
            assert 'Preview only' in page.locator('#garage-state').inner_text()
            page.screenshot(path=str(out/'garage-empty.png'))
            page.locator('#garage-presence').select_option('live')
            page.evaluate('async()=>{await chfHouseRefresh()}')
            payload['garage']['cars'][0]['present'] = False
            page.evaluate('async()=>{await chfHouseRefresh()}'); occupied(False)
            page.locator('#garage-presence').select_option('home'); occupied(True)
            assert not writes, writes
            page.locator('#hybrid-outside').click(); mode('exterior')
            page.go_forward(); mode('garage')
            page.reload(); mode('garage'); occupied(False)
            page.set_viewport_size({'width':390,'height':844})
            page.locator('#garage-presence').select_option('home'); occupied(True)
            for selector in ('#garage-presence','#garage-fleet','#hybrid-outside'):
                box = page.locator(selector).bounding_box()
                assert box and box['x'] >= 0 and box['x'] + box['width'] <= 390, (selector,box)
            page.screenshot(path=str(out/'garage-phone.png'))
            page.locator('#garage-car').tap()
            page.wait_for_selector('#garage-dashboard:visible')
            page.screenshot(path=str(out/'garage-dashboard-phone.png'))
            page.keyboard.press('Escape')
            assert page.locator('#garage-dashboard').is_hidden()
            page.locator('#hybrid-outside').tap(); mode('exterior')
            page.locator('#exterior-garage-marker').tap()
            page.locator('[data-preview="cars"]').focus(); page.keyboard.press('Shift+Enter')
            mode('garage')
            page.locator('#hybrid-outside').tap(); mode('exterior')
            page.emulate_media(reduced_motion='no-preference')
            page.locator('#exterior-garage-marker').tap()
            box = page.locator('[data-preview="cars"]').bounding_box()
            page.mouse.move(box['x'] + box['width']/2, box['y'] + 25)
            page.mouse.down(); page.wait_for_timeout(550); page.mouse.up()
            mode('entering'); mode('garage')
            # Without an explicit artwork-to-car binding, the stock scene does
            # not infer identity from a matching model name or fabricate values.
            page.goto(served.url('house?compare=exterior&light=day&scene=garage'))
            mode('garage')
            page.locator('#garage-car').click()
            page.wait_for_selector('#garage-dashboard:visible')
            assert page.locator('#cluster-energy').inner_text() == '—'
            assert page.locator('#cluster-presence').inner_text() == 'PREVIEW'
            assert not served.errors(), served.errors()
            print('PASS: garage marker, cards, presence, preview isolation, history, reload, keyboard and phone')
    finally:
        served.stop()


if __name__ == '__main__':
    main()
