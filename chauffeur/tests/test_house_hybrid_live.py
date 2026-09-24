"""Hybrid camera destinations: live controls, navigation, sun, touch and no WebGL.

Run from chauffeur/: python tests/test_house_hybrid_live.py --out <directory>
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(ROOT / 'tools')]
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_hybrid_')

from house_probe import _seed
from live_app import live_app
from services import ha_api, storage


def seed():
    _seed()
    storage.add_household_task({'id': 'hybrid-task', 'title': 'Replace the air filter',
                                'due_date': '2020-01-01', 'status': 'open'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=tempfile.mkdtemp(prefix='hybrid_shots_'))
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    assert served, 'Playwright required for the comparison review'
    from services import house_room
    payload = house_room.state(since_ts=0)
    payload['window'] = {'night': False, 'next_sun_change': None}
    results = {}
    def check_full_viewport(page):
        assert page.locator('#hybrid-room-frame').evaluate('''el => {
            const r=el.getBoundingClientRect(), css=getComputedStyle(el);
            return r.x===0 && r.y===0 && r.width===innerWidth && r.height===innerHeight
                && css.borderRadius==='0px' && css.borderTopWidth==='0px';
        }'''), 'hybrid must fill the same viewport as the 3D canvas'
        assert page.locator('#hybrid-day').evaluate("el=>getComputedStyle(el).objectFit==='cover'")
    try:
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            page.set_default_timeout(30000)
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(
                status=204, content_type='text/event-stream', body=''))
            page.route('**/api/music/favorites*', lambda r: r.fulfill(
                status=200, content_type='application/json', body='{"items":[]}'))
            page.route('**/api/house/state*', lambda r: r.fulfill(
                status=200, content_type='application/json', body=json.dumps(payload)))
            page.add_init_script('''(() => {
                if (new URL(location.href).searchParams.get('render') === '3d') return;
                window.webglAttempts=0;
                const original=HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext=function(kind,...args){
                    if (/webgl|experimental-webgl/.test(kind)) { window.webglAttempts++; return null; }
                    return original.call(this,kind,...args);
                };
            })();''')
            page.goto(served.url('house?compare=living&quality=low'), wait_until='domcontentloaded')
            page.wait_for_function('window.chfHouseComparison?.readyMs > 0')
            assert page.evaluate('typeof THREE') == 'undefined'
            assert page.evaluate('webglAttempts') == 0
            check_full_viewport(page)
            assert 'compare=' not in page.locator('#house-compare-exit').get_attribute('href')
            resources = page.evaluate('performance.getEntriesByType("resource").map(r=>({name:r.name,size:r.encodedBodySize}))')
            assert not any('/three.min.js' in r['name'] or '/house.js?' in r['name'] for r in resources)
            assert len([r for r in resources if '/house_hybrid/' in r['name']]) == 1
            results['hybrid'] = page.evaluate('chfHouseComparison')
            results['hybrid']['resourceBytes'] = sum(r['size'] for r in resources)
            page.screenshot(path=str(out / 'hybrid-day-desktop.png'))
            desktop = page.locator('#hybrid-hotspots [data-card]')
            assert desktop.count() == 4
            # Marker coordinates must follow cover cropping, not viewport %.
            for width, height in ((2560, 1080), (1400, 1000)):
                page.set_viewport_size({'width':width,'height':height})
                page.wait_for_function('''() => {
                    const el=document.querySelector('#hybrid-hotspots [data-card="music"]');
                    const r=el.getBoundingClientRect(), scale=Math.max(innerWidth/1536,innerHeight/1024);
                    return Math.abs(r.x+r.width/2-(.218*1536*scale+(innerWidth-1536*scale)/2))<1
                        && Math.abs(r.y+r.height/2-(.256*1024*scale+(innerHeight-1024*scale)/2))<1;
                }''')
                check_full_viewport(page)
                if width == 2560:
                    page.screenshot(path=str(out / 'hybrid-wide-desktop.png'))
            for key in ('music', 'pets', 'tasks', 'programs'):
                trigger = page.locator(f'#hybrid-hotspots [data-card="{key}"]')
                trigger.click()
                page.wait_for_selector(f'#hybrid-room-frame[data-view="{key}"][data-phase="detail"]')
                surface = page.locator('#house-radio' if key == 'music' else '#house-book' if key in ('tasks', 'programs') else '#house-life .house-life-panel')
                surface.wait_for(state='visible')
                check_full_viewport(page)
                assert page.locator('#house-life [role="dialog"]').count() == 0
                assert page.locator(f'#hybrid-detail img[data-view="{key}"][data-light="day"]').evaluate('(el)=>el.naturalWidth > 0 && el.classList.contains("is-active")')
                page.wait_for_function("!Alpine.$data(document.getElementById('house-life')).loading")
                if key == 'tasks':
                    page.get_by_text('Replace the air filter', exact=True).wait_for(state='visible')
                    assert page.get_by_role('button', name='Manage with parent PIN').is_visible()
                page.screenshot(path=str(out / (key + '-day-desktop.png')))
                page.locator('#house-compare-light').select_option('night')
                page.wait_for_selector('#hybrid-detail[data-light="night"]')
                assert page.locator(f'#hybrid-detail img[data-view="{key}"][data-light="night"]').evaluate('(el)=>el.naturalWidth > 0 && el.classList.contains("is-active")')
                assert surface.is_visible()
                page.screenshot(path=str(out / (key + '-night-desktop.png')))
                if key == 'tasks':
                    page.go_back()
                elif key == 'music':
                    page.keyboard.press('Escape')
                elif key == 'programs':
                    page.locator('#hybrid-view-back').click()
                else:
                    page.get_by_role('button', name='Return to living room', exact=True).click()
                page.wait_for_selector('#hybrid-room-frame[data-view="room"][data-phase="room"]')
                surface.wait_for(state='hidden')
                assert trigger.evaluate('(el)=>document.activeElement === el')
                page.locator('#house-compare-light').select_option('day')
            before = [desktop.nth(i).bounding_box() for i in range(4)]
            page.locator('#house-compare-light').select_option('night')
            page.wait_for_selector('#hybrid-room-frame[data-light="night"]')
            assert before == [desktop.nth(i).bounding_box() for i in range(4)]
            page.screenshot(path=str(out / 'hybrid-night-desktop.png'))
            payload['window']['next_sun_change'] = (datetime.now(timezone.utc) + timedelta(seconds=4)).isoformat()
            page.evaluate('chfHouseRefresh()')
            page.locator('#house-compare-light').select_option('auto')
            page.wait_for_selector('#hybrid-room-frame[data-light="day"]')
            page.wait_for_selector('#hybrid-room-frame[data-light="night"]', timeout=12000)
            page.set_viewport_size({'width': 390, 'height': 844})
            check_full_viewport(page)
            shortcuts = page.locator('#hybrid-shortcuts [data-card]')
            for i in range(4):
                box = shortcuts.nth(i).bounding_box()
                assert box and box['width'] >= 44 and box['height'] >= 44
                shortcuts.nth(i).tap()
                page.wait_for_selector('#hybrid-room-frame[data-phase="detail"]')
                key = shortcuts.nth(i).get_attribute('data-card')
                page.locator('#house-radio' if key == 'music' else '#house-book' if key in ('tasks', 'programs') else '#house-life .house-life-panel').wait_for(state='visible')
                check_full_viewport(page)
                page.screenshot(path=str(out / ('detail-' + str(i) + '-phone.png')))
                page.locator('#hybrid-view-back').tap()
                page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(out / 'hybrid-night-phone.png'))
            assert not served.errors(), served.errors()
            page.set_viewport_size({'width': 1400, 'height': 1000})
            page.emulate_media(reduced_motion='no-preference')
            page.locator('#hybrid-hotspots [data-card="music"]').click()
            page.wait_for_selector('#hybrid-room-frame[data-phase="entering"]')
            assert page.locator('#hybrid-overview').evaluate('(el)=>getComputedStyle(el).transform') != 'none'
            page.screenshot(path=str(out / 'approach-radio.png'))
            page.wait_for_selector('#hybrid-room-frame[data-phase="detail"]')
            page.locator('#hybrid-view-back').click()
            page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            page.emulate_media(reduced_motion='reduce')
            page.locator('[data-render="3d"]').click()
            page.wait_for_function('window.chfHouseComparison?.renderer === "3d" && chfHouseComparison.readyMs > 0', timeout=120000)
            assert page.evaluate('chfHouseMode()') == 'living'
            assert 'quality=low' in page.url
            page.locator('.house-hint[data-house-action="tasks"]').click()
            page.locator('#house-life [role="dialog"]').wait_for(state='visible')
            page.get_by_text('Replace the air filter', exact=True).wait_for(state='visible')
            page.get_by_role('button', name='Close and return to house').click()
            page.locator('#house-life [role="dialog"]').wait_for(state='hidden')
            results['3d-low'] = page.evaluate('chfHouseComparison')
            results['3d-low']['resourceBytes'] = page.evaluate('performance.getEntriesByType("resource").reduce((n,r)=>n+r.encodedBodySize,0)')
            page.screenshot(path=str(out / '3d-low-desktop.png'))
            assert 'render=hybrid' in page.locator('[data-render="hybrid"]').get_attribute('href')
            page.locator('[data-render="hybrid"]').click()
            try:
                page.wait_for_function('window.chfHouseComparison?.renderer === "hybrid" && chfHouseComparison.readyMs > 0')
            except Exception:
                print('Failed return', page.url, page.evaluate('window.chfHouseComparison'), served.errors(), flush=True)
                page.screenshot(path=str(out / 'return-failed.png'))
                raise
            assert page.evaluate('typeof THREE') == 'undefined'
            assert not served.errors(), served.errors()
            # A late image must not reopen a destination after the user left it.
            held = []
            page.route('**/ledger-pages-day.png*', lambda route: held.append(route))
            page.goto(served.url('house?compare=living&light=day'), wait_until='domcontentloaded')
            page.wait_for_function('window.chfHouseComparison?.readyMs > 0')
            page.locator('#hybrid-hotspots [data-card="tasks"]').click()
            page.wait_for_selector('#hybrid-room-frame[data-phase="loading"]')
            page.locator('#hybrid-view-back').click()
            page.wait_for_selector('#hybrid-room-frame[data-phase="room"]')
            assert held, 'the destination request must have been held'
            for route in held:
                route.fulfill(status=200, content_type='image/png', path=str(ROOT / 'static/house_hybrid/ledger-pages-day.png'))
            page.wait_for_function('document.querySelector("#hybrid-detail img[data-view=tasks][data-light=day]").naturalWidth > 0')
            assert page.locator('#hybrid-room-frame').get_attribute('data-phase') == 'room'
            assert not page.locator('#house-book').is_visible()
            assert not served.errors(), served.errors()
        (out / 'stats.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(results, indent=2), flush=True)
        print('PASS: four day/night perspectives, in-scene controls, animated/reduced-motion navigation, focus, sun boundary, touch, no-WebGL and renderer switch', flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    main()
