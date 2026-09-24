"""Eight saved exterior angles connect to existing hybrid rooms without WebGL."""
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
            page.add_init_script('''window.webglAttempts=0;
                const context=HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext=function(kind,...args){
                    if (/webgl/.test(kind)) { window.webglAttempts++; return null; }
                    return context.call(this,kind,...args);
                };''')
            def mode(value):
                page.wait_for_function('(m)=>window.chfExteriorProbe?.().mode===m', arg=value)
            def angle(value):
                page.wait_for_function('(a)=>window.chfExteriorProbe?.().angle===a', arg=value)
            page.goto(served.url('house?compare=exterior&light=day'))
            angle(0)
            assert page.locator('#hybrid-room').evaluate('el=>el.inert')
            assert page.evaluate('typeof THREE') == 'undefined'
            assert page.evaluate('webglAttempts') == 0
            assert page.locator('#exterior-pictures').bounding_box() == {'x':0,'y':0,'width':1400,'height':1000}
            for value in range(8):
                page.locator(f'#exterior-stops [data-angle="{value}"]').click()
                angle(value)
                assert page.locator('#exterior-pictures img.is-active').count() == 1
            page.keyboard.press('ArrowRight')
            angle(0)
            page.keyboard.press('ArrowLeft')
            angle(7)
            # Repeated input must end on the last requested angle.
            page.evaluate("for(let i=0;i<4;i++)document.getElementById('exterior-right').click()")
            angle(3)
            page.locator('#exterior-stops [data-angle="0"]').click()
            angle(0)
            page.screenshot(path=str(out/'exterior-desktop.png'))
            page.evaluate('window.documentToken="same-document"')
            page.locator('#exterior-enter').click()
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
            angle(0)
            page.go_forward()
            mode('living')
            page.locator('#hybrid-outside').click()
            mode('exterior')
            assert page.evaluate('documentToken') == 'same-document'
            # Deep links/reloads preserve both scene and exterior angle.
            page.goto(served.url('house?compare=exterior&light=day&angle=6&scene=living'))
            mode('living')
            angle(6)
            page.reload()
            mode('living')
            assert 'scene=living' in page.url
            page.locator('#hybrid-outside').click()
            mode('exterior')
            angle(6)
            page.set_viewport_size({'width':390,'height':844})
            assert page.locator('#exterior-enter').is_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            # Touch pointer events use the same swipe path as a phone.
            surface = page.locator('#house-exterior')
            surface.dispatch_event('pointerdown', {'pointerId':1,'isPrimary':True,'button':0,'clientX':300,'clientY':450})
            surface.dispatch_event('pointerup', {'pointerId':1,'isPrimary':True,'button':0,'clientX':100,'clientY':450})
            angle(7)
            page.screenshot(path=str(out/'exterior-phone.png'))
            page.locator('#exterior-enter').tap()
            mode('living')
            page.locator('#hybrid-shortcuts [data-card="music"]').tap()
            page.wait_for_selector('#hybrid-room-frame[data-view="music"][data-phase="detail"]')
            page.locator('#hybrid-view-back').tap()
            page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            page.locator('#hybrid-outside').tap()
            mode('exterior')
            assert page.evaluate('webglAttempts') == 0
            assert not served.errors(), served.errors()
            # Deliberate missing asset retains the last good image and can retry.
            page.route('**/exterior-orbit/view-4.jpg*', lambda r:r.abort())
            page.goto(served.url('house?compare=exterior&light=day'))
            angle(0)
            page.locator('#exterior-stops [data-angle="4"]').tap()
            page.wait_for_function("document.getElementById('exterior-status').textContent.includes('could not load')")
            angle(0)
            page.unroute('**/exterior-orbit/view-4.jpg*')
            page.locator('#exterior-stops [data-angle="4"]').tap()
            angle(4)
            # Exercise the actual transition as well as reduced motion.
            page.emulate_media(reduced_motion='no-preference')
            page.locator('#exterior-enter').tap()
            mode('entering')
            mode('living')
            assert not [e for e in served.errors() if 'net::ERR_FAILED' not in e], served.errors()
            (out/'results.json').write_text(json.dumps({'passed':True,'views':8,'webglAttempts':0}, indent=2))
            print('PASS: exterior orbit, room destinations, history, reload, touch, motion and asset retry')
    finally:
        served.stop()


if __name__ == '__main__':
    main()
