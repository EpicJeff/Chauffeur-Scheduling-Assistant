"""Perspective paper interactions and accessible, bounded household constellations."""
import argparse
from pathlib import Path
from test_house_connected_live import seed, live_app, ha_api, storage
from services import study


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', required=True)
    out = Path(parser.parse_args().out).resolve(); out.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    try:
        with served.browser(has_touch=True, reduced_motion='no-preference') as page:
            page.set_default_timeout(20000)
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
            def enter(key):
                host = '.utility-shortcuts' if page.viewport_size['width'] < 701 else '.utility-hotspots'
                page.locator(f'#hybrid-study {host} [data-card={key}]').click()
                page.wait_for_selector('#hybrid-study[data-phase=detail]')
            def back():
                page.locator('#hybrid-study .utility-back').click()
                page.wait_for_function('!history.state?.chfUtilityView')
            def frames(): return int(page.locator('.constellation-sky canvas').get_attribute('data-frames'))
            def still():
                page.wait_for_timeout(100)
                first = frames(); page.wait_for_timeout(250)
                assert frames() == first
            page.goto(served.url('house?compare=exterior&scene=living&light=day'))
            page.wait_for_function("chfHouseMode()==='living'")
            page.locator('#hybrid-walkthrough [data-room=study]').click()
            page.wait_for_selector('#cc-input-field:visible')
            page.fill('#cc-input-field', '1234'); page.click('#cc-input-ok-btn')
            page.wait_for_function("chfHouseMode()==='study'")
            for key in ('tray', 'desk'):
                enter(key)
                # Real perspective, with the top edge narrower than the bottom.
                assert page.locator('#study-controls').evaluate('''e=>{
                    const m=new DOMMatrix(getComputedStyle(e).transform),w=e.offsetWidth,h=e.offsetHeight;
                    const point=(x,y)=>{const p=new DOMPoint(x,y).matrixTransform(m);return {x:p.x/p.w,y:p.y/p.w}};
                    const a=point(0,0),b=point(w,0),c=point(w,h),d=point(0,h);
                    return (b.x-a.x)/(c.x-d.x)<.9 && a.x>d.x && c.x>b.x;
                }''')
                page.screenshot(path=str(out/f'{key}-perspective.png')); back()
            enter('monitor')
            people = page.locator('.constellation-person')
            assert people.count() == 3
            page.get_by_role('button', name='Alex: 5 calendar items this week', exact=True).hover()
            assert page.locator('.constellation-readout').inner_text() == 'Alex\n5 calendar items this week'
            page.get_by_role('button', name='Maya: 3 calendar items this week', exact=True).focus()
            assert page.locator('.constellation-readout strong').inner_text() == 'Maya'
            page.get_by_role('button', name='Jordan: 4 calendar items this week', exact=True).tap()
            assert page.locator('.constellation-readout span').inner_text() == '4 calendar items this week'
            first = frames()
            page.wait_for_function('(n)=>+document.querySelector(".constellation-sky canvas").dataset.frames>n+3', arg=first)
            page.screenshot(path=str(out/'constellations-day.png'))
            page.get_by_role('button', name='Pause motion', exact=True).click(); still()
            page.evaluate("chfUtilityRooms.ready('study')")
            page.get_by_role('button', name='Resume motion', exact=True).wait_for(); still()
            page.get_by_role('button', name='Resume motion', exact=True).click()
            first = frames()
            page.wait_for_function('(n)=>+document.querySelector(".constellation-sky canvas").dataset.frames>n+3', arg=first)
            page.emulate_media(reduced_motion='reduce'); still()
            assert page.get_by_role('button', name='Motion reduced', exact=True).is_disabled()
            page.locator('#house-compare-light').select_option('night')
            page.wait_for_selector('#hybrid-study .utility-plane img.is-active[data-light=night]')
            page.screenshot(path=str(out/'constellations-night.png'))
            page.emulate_media(reduced_motion='no-preference')
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'))")
            still()
            page.evaluate("delete document.hidden;document.dispatchEvent(new Event('visibilitychange'))")
            page.evaluate("window.oldConstellation=document.querySelector('.constellation-sky canvas')")
            back()
            old_frames = page.evaluate('oldConstellation.dataset.frames')
            page.wait_for_timeout(200)
            assert page.evaluate('oldConstellation.dataset.frames') == old_frames
            assert page.locator('.constellation-person').count() == 0
            page.set_viewport_size({'width':390, 'height':844})
            page.locator('#house-compare-light').select_option('day')
            # The perspective input remains editable and persists through the real API on touch.
            enter('tray')
            title = page.get_by_label('Title', exact=True)
            title.fill('Perspective phone edit')
            page.get_by_role('button', name='Approve & file', exact=True).tap()
            page.wait_for_function("document.querySelector('.study-feedback')?.textContent && !document.querySelector('.study-feedback').textContent.includes('Saving')")
            assert any(t['title']=='Perspective phone edit' for t in storage.get_household_tasks())
            page.screenshot(path=str(out/'intake-phone.png')); back()
            enter('desk')
            page.get_by_role('button', name='Mark done', exact=True).first.tap()
            page.wait_for_function("document.querySelector('.study-feedback')?.textContent && !document.querySelector('.study-feedback').textContent.includes('Saving')")
            assert next(r for r in storage.get_mind_insights() if r['id']=='demo-plan')['plan_json']['steps'][0]['status']=='done'
            page.screenshot(path=str(out/'plans-phone.png')); back()
            enter('monitor')
            page.get_by_role('button', name='Alex: 5 calendar items this week', exact=True).tap()
            page.screenshot(path=str(out/'constellations-phone.png')); back()
            # Eight members, zero, unknown and a large count must remain truthful and reachable.
            original = study.state
            rows = [{'name':f'Person {i}', 'count':n} for i,n in enumerate([0,None,1,3,5,7,12,100])]
            def custom(*args, **kwargs):
                data = original(*args, **kwargs)
                data['furniture']['monitor']['clusters'] = rows
                return data
            study.state = custom
            page.evaluate("chfUtilityRooms.ready('study')")
            enter('monitor'); page.wait_for_function("document.querySelectorAll('.constellation-person').length===8")
            assert people.evaluate_all('els=>els.every(e=>e.offsetWidth>=44&&e.offsetHeight>=44)')
            people.nth(0).tap(); assert page.locator('.constellation-readout span').inner_text() == '0 calendar items this week'
            people.nth(1).focus(); assert page.locator('.constellation-readout span').inner_text() == 'Calendar activity is unavailable.'
            people.nth(7).tap(); assert page.locator('.constellation-readout span').inner_text() == '100 calendar items this week'
            page.screenshot(path=str(out/'eight-people-phone.png')); back()
            rows = []
            page.evaluate("chfUtilityRooms.ready('study')")
            enter('monitor'); page.get_by_text('A quiet sky', exact=True).wait_for()
            assert people.count() == 0
            assert page.locator('.constellation-toggle').is_hidden()
            back(); study.state = original
            page.evaluate("chfUtilityRooms.ready('study')")
            enter('monitor'); page.wait_for_function("document.querySelectorAll('.constellation-person').length===3")
            page.evaluate("window.oldConstellation=document.querySelector('.constellation-sky canvas')")
            page.click('#study-lock'); page.wait_for_function("chfHouseMode()==='living'")
            old_frames = page.evaluate('oldConstellation.dataset.frames')
            page.wait_for_timeout(200)
            assert page.evaluate('oldConstellation.dataset.frames') == old_frames
            assert not page.locator('#study-controls').inner_text()
            assert not served.errors(), served.errors()
            print('PASS: perspective desktop/touch writes; hover/focus/tap counts; animation/pause/reduced motion/visibility; eight/zero/unknown members; day/night; disposal and lock')
    finally: served.stop()


if __name__ == '__main__': main()
