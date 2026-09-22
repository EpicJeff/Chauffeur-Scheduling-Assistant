"""Exterior quick views and intentional zone visits with real pointer events."""
import os
import sys
import tempfile
from pathlib import Path
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='house_markers_'))
from live_app import live_app
from house_live_common import _seed
from services import ha_api


def main():
    ha_api.get_states = lambda *a, **k: []
    ha_api.get_state = lambda *a, **k: None
    served = live_app(_seed)
    try:
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=200, body=''))
            page.goto(served.url('house')+'?quality=low&day=1', wait_until='domcontentloaded', timeout=120000)
            page.wait_for_function('window.chfNavProbe && chfNavProbe({settled:true})', timeout=120000)
            for room in ['kitchen','living','mudroom','garage','study']:
                marker=page.locator(f'.house-hint[data-room="{room}"]')
                marker.click()
                assert marker.get_attribute('aria-expanded') == 'true'
                assert page.evaluate('chfHouseMode()') == 'exterior'
                keys=page.locator('.house-marker-feature').evaluate_all('(els)=>els.map(e=>e.dataset.preview)')
                for key in keys:
                    page.locator(f'[data-preview="{key}"]').click()
                    page.wait_for_selector('.house-life-panel:visible')
                    page.wait_for_function("!Alpine.$data(document.querySelector('#house-life')).loading")
                    assert page.evaluate('chfHouseMode()') == 'exterior'
                    assert page.locator('.house-life-panel').inner_text().strip()
                    page.get_by_role('button', name='Close and return to house').click()
                    assert marker.get_attribute('aria-expanded') == 'true'
                print('PASS previews',room,flush=True)
            page.keyboard.press('Escape')
            page.set_viewport_size({'width':390,'height':844})
            marker=page.locator('.house-hint[data-room="kitchen"]')
            marker.tap()
            boxes=page.locator('.house-marker-feature').evaluate_all('(els)=>els.map(e=>{const r=e.getBoundingClientRect();return [r.left,r.top,r.right,r.bottom];})')
            assert all(0<=x<right<=390 and 0<=y<bottom<=844 for x,y,right,bottom in boxes),boxes
            path=Path(tempfile.gettempdir())/'chauffeur-expanded-markers.png'
            page.screenshot(path=str(path));print('SCREENSHOT',path,flush=True)
            button=page.locator('[data-preview="moments"]')
            box=button.bounding_box();x=box['x']+box['width']/2;y=box['y']+25
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+35,y);page.mouse.up()
            assert not page.locator('.house-life-panel').is_visible()
            assert page.evaluate('chfHouseMode()') == 'exterior'
            page.mouse.move(x,y);page.mouse.down();page.wait_for_timeout(650);page.mouse.up()
            page.wait_for_function("chfHouseMode()==='kitchen' && chfNavProbe({settled:true})",timeout=30000)
            assert not page.locator('.house-life-panel').is_visible()
            print('PASS mobile layout, drag cancellation and hold visit',flush=True)
            page.evaluate('chfHouseExit()')
            page.wait_for_function('chfNavProbe({settled:true})',timeout=30000)
            marker=page.locator('.house-hint[data-room="living"]')
            marker.click();marker.click()
            page.wait_for_function("chfHouseMode()==='living' && chfNavProbe({settled:true})",timeout=30000)
            page.evaluate('chfHouseExit()')
            page.wait_for_function('chfNavProbe({settled:true})',timeout=30000)
            page.locator('.house-hint[data-room="living"]').click()
            page.locator('[data-preview="tasks"]').focus()
            page.keyboard.press('Shift+Enter')
            page.wait_for_function("chfHouseMode()==='living' && chfNavProbe({settled:true})",timeout=30000)
            assert not page.locator('.house-life-panel').is_visible()
            assert page.evaluate("chfNavProbe({feature:'tasks'})") is not None
            assert not errors,errors
            print('PASS second marker tap enters room; no browser errors',flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    main()
