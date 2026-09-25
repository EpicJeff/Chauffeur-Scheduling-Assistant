"""Real House landing and board fallback, isolated from household data."""
import os
import json
import sys
import tempfile
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='house_home_'))
from live_app import live_app
from house_live_common import _seed
from services import ha_api, storage


def verify_config(served):
    storage.add_member({'id':'home-admin','name':'Home Admin','role':'parent'})
    token = storage.create_member_token('home-admin')
    with served.browser() as page:
        page.add_init_script('localStorage.setItem("chauffeur_member_token", '+json.dumps(token)+')')
        page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=200, body=''))
        page.goto(served.url('config'), wait_until='domcontentloaded')
        page.get_by_role('button', name='Boards', exact=True).click()
        page.wait_for_function("Alpine.$data(document.querySelector('#boards')).panelLoaded")
        assert not page.locator('#panel-house-home').is_checked()
        with page.expect_response(lambda r: '/api/settings' in r.url and r.request.method == 'POST') as response:
            page.locator('#panel-house-home').check()
        assert response.value.ok
        assert storage.get_settings()['panel_house_home'] is True
        page.reload(wait_until='domcontentloaded')
        page.get_by_role('button', name='Boards', exact=True).click()
        page.wait_for_function("Alpine.$data(document.querySelector('#boards')).panelLoaded")
        assert page.locator('#panel-house-home').is_checked()
        assert not page.locator('#house-hybrid-enabled').is_checked()
        with page.expect_response(lambda r: '/api/settings' in r.url and r.request.method == 'POST') as response:
            page.locator('#house-hybrid-enabled').check()
        assert response.value.ok
        assert storage.get_settings()['house_hybrid_enabled'] is True
        page.reload(wait_until='domcontentloaded')
        page.get_by_role('button', name='Boards', exact=True).click()
        page.wait_for_function("Alpine.$data(document.querySelector('#boards')).panelLoaded")
        assert page.locator('#panel-house-home').is_checked()
        assert page.locator('#house-hybrid-enabled').is_checked()
        shots=Path('../scratch/house-choice'); shots.mkdir(parents=True,exist_ok=True)
        page.locator('#panel-house-home').scroll_into_view_if_needed()
        page.screenshot(path=str(shots/'settings-desktop.png'))
        with page.expect_response(lambda r: '/api/settings' in r.url and r.request.method == 'POST') as response:
            page.locator('#house-hybrid-enabled').uncheck()
        assert response.value.ok
        assert storage.get_settings()['house_hybrid_enabled'] is False
        assert storage.get_settings()['panel_house_home'] is True
        print('PASS: both config toggles persist independently; hybrid can be disabled', flush=True)
        page.evaluate("Alpine.$data(document.querySelector('#boards')).openBoard({slug:'home'})")
        page.wait_for_url('**/home?panel=false&home_view=board', timeout=30000)
        assert page.locator('#room canvas').count() == 0
        print('PASS: Boards editor can still open the Home board', flush=True)


def verify_hybrid(served):
    storage.patch_settings({'panel_house_home': True, 'house_hybrid_enabled': True,
                            'panel_idle_return_seconds': 0})
    with served.browser(reduced_motion='reduce') as page:
        page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
        page.add_init_script("""sessionStorage.setItem('chauffeur_house_unavailable','1');
            HTMLCanvasElement.prototype.getContext=function(){return null;};""")
        page.goto(served.url('home?panel=true&quality=2d'), wait_until='domcontentloaded')
        page.wait_for_url('**/house?*')
        page.wait_for_function('window.chfExteriorProbe?.().ready')
        assert 'compare=' not in page.url
        assert page.locator('body').get_attribute('data-house-render') == 'hybrid'
        assert page.locator('#house-comparison').is_hidden()
        assert page.locator('#house-compare-measurements').is_hidden()
        assert page.evaluate('typeof THREE') == 'undefined'
        shots=Path('../scratch/house-choice'); shots.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(shots/'default-house-desktop.png'))
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(shots/'default-house-phone.png'))
        page.set_viewport_size({'width':1400,'height':1000})
        page.evaluate("chfHybridGo('living')")
        page.wait_for_function("chfHouseMode()==='living'")
        assert page.locator('#house-comparison').is_hidden()
        page.locator('#hybrid-walkthrough [data-room=kitchen]').click()
        page.wait_for_function("chfHouseMode()==='kitchen'")
        assert page.evaluate('ChauffeurHome.rest()')
        page.wait_for_function("chfHouseMode()==='exterior'")
        assert 'scene=' not in page.url
        # Room state carried to another panel page must not change Home's destination.
        page.goto(served.url('chores?panel=true&scene=living&angle=90&light=night'),wait_until='domcontentloaded')
        home_link=page.locator('#panel-shelf a[data-slug="home"]')
        home_link.wait_for(state='visible')
        assert 'scene=living' in home_link.get_attribute('href'), 'Exercise the intentionally inherited query'
        home_link.click()
        page.wait_for_url('**/house?*')
        page.wait_for_function("window.chfHouseMode?.()==='exterior' && window.chfExteriorProbe?.().ready")
        assert 'scene=' not in page.url and 'angle=' not in page.url
        assert 'panel=true' in page.url and 'light=night' in page.url
        page.goto(served.url('house?panel=true&scene=living'),wait_until='domcontentloaded')
        page.wait_for_function("window.chfHouseMode?.()==='living'")
        other_context = page.context.browser.new_context(reduced_motion='reduce')
        try:
            other = other_context.new_page()
            other.goto(served.url('house'), wait_until='domcontentloaded')
            assert other.locator('body').get_attribute('data-house-render') == 'hybrid'
        finally:
            other_context.close()
        for query in ('editor=1&quality=2d', 'draft=expired&quality=2d', 'render=3d&quality=2d'):
            page.goto(served.url('house?'+query), wait_until='domcontentloaded')
            assert page.locator('#house-exterior').count() == 0, query
        storage.patch_settings({'panel_house_home': False})
        page.goto(served.url('home'), wait_until='domcontentloaded')
        assert page.evaluate('typeof ChauffeurHome') == 'undefined'
        page.goto(served.url('house'), wait_until='domcontentloaded')
        assert page.locator('body').get_attribute('data-house-render') == 'hybrid'
        storage.patch_settings({'house_hybrid_enabled': False})
        page.reload(wait_until='domcontentloaded')
        assert page.locator('#house-exterior').count() == 0
        assert page.locator('body').get_attribute('data-house-render') is None
        page.goto(served.url('house?compare=exterior&scene=living'), wait_until='domcontentloaded')
        page.wait_for_function("window.chfHouseMode?.()==='living'")
        assert page.locator('body').get_attribute('data-house-render') == 'hybrid'
        assert page.locator('#house-comparison').is_visible()
    print('PASS: household hybrid default, no-WebGL Home, idle return, second device, editor isolation and rollback', flush=True)


def main():
    ha_api.get_states = lambda *a, **k: []
    ha_api.get_state = lambda *a, **k: None
    def seed():
        _seed()
        storage.patch_settings({'panel_house_home': True, 'panel_screensaver_enabled': False,
                                'panel_idle_return_seconds': 0})
    served = live_app(seed)
    if not served:
        raise RuntimeError('Browser unavailable')
    import main as app_main
    app_main.trigger_background_refresh = lambda *a, **k: None
    try:
        with served.browser(reduced_motion='reduce') as page:
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=200, body=''))
            page.goto(served.url('home')+'?panel=true&quality=low', wait_until='domcontentloaded', timeout=120000)
            page.wait_for_url('**/house?*', timeout=30000)
            page.wait_for_function('window.chfNavProbe && chfNavProbe({settled:true})', timeout=120000)
            assert page.locator('#room canvas').count() == 1
            print('PASS: enabled Home opens real 3D House', flush=True)
            page.evaluate("chfHouseEnterRoom('kitchen')")
            page.wait_for_function('chfNavProbe({settled:true})', timeout=30000)
            assert page.evaluate('ChauffeurHome.rest()')
            page.wait_for_function("chfHouseMode()==='exterior' && chfOrbitStop()===0 && chfNavProbe({settled:true})", timeout=30000)
            assert '/house?' in page.url
            storage.patch_settings({'panel_idle_return_seconds': 15})
            page.add_init_script("localStorage.setItem('chfPanelLastInput', String(Date.now()))")
            page.goto(served.url('house')+'?panel=true&quality=low&angle=5', wait_until='domcontentloaded')
            page.wait_for_function('window.chfNavProbe && chfNavProbe({settled:true})', timeout=120000)
            assert page.evaluate('chfOrbitStop()') == 5
            page.evaluate('window.__homeIdleMarker = true')
            page.wait_for_function('chfOrbitStop()===0 && chfNavProbe({settled:true})', timeout=40000)
            assert page.evaluate('window.__homeIdleMarker === true')
            assert '/house?' in page.url
            print('PASS: actual idle timer resets the House without reloading', flush=True)
            page.evaluate("document.querySelector('#room canvas').dispatchEvent(new Event('webglcontextlost',{cancelable:true}))")
            page.wait_for_url('**/home?**home_view=board', timeout=30000)
            assert 'panel=true' in page.url
            page.goto(served.url('home')+'?panel=true', wait_until='domcontentloaded')
            assert '/home?' in page.url
            assert page.evaluate("sessionStorage.getItem('chauffeur_house_unavailable')") == '1'
            print('PASS: context loss returns to board and Home does not retry', flush=True)
        with served.browser(reduced_motion='reduce') as page:
            page.add_init_script("""const get = HTMLCanvasElement.prototype.getContext;
                HTMLCanvasElement.prototype.getContext = function(type,...args) {
                    return type.startsWith('webgl') ? null : get.call(this,type,...args);
                };""")
            page.goto(served.url('home')+'?panel=true', wait_until='domcontentloaded')
            assert '/home?' in page.url
            page.goto(served.url('house')+'?panel=true', wait_until='domcontentloaded')
            page.wait_for_url('**/home?**home_view=board', timeout=30000)
            page.goto(served.url('house')+'?editor=1&quality=2d', wait_until='domcontentloaded')
            page.wait_for_function("document.querySelector('#fallback-rows').children.length>0")
            assert '/house?' in page.url
            print('PASS: unsupported hardware falls back; editor stays isolated', flush=True)
            storage.patch_settings({'panel_house_home': False})
            page.goto(served.url('home'), wait_until='domcontentloaded')
            assert page.evaluate('typeof window.ChauffeurHome') == 'undefined'
            page.goto(served.url('house')+'?quality=2d', wait_until='domcontentloaded')
            page.wait_for_function("document.querySelector('#fallback-rows').children.length>0")
            assert '/house?' in page.url
            print('PASS: toggle off preserves existing Home and House behavior', flush=True)
        verify_config(served)
        verify_hybrid(served)
    finally:
        served.stop()


if __name__ == '__main__':
    main()
