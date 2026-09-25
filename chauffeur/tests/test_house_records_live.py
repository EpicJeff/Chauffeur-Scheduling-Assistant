"""Record shelf and search: real UI/shared music logic, intercepted music APIs."""
from playwright.sync_api import expect
import json
import base64
from pathlib import Path
from urllib.parse import urlparse
from test_house_hybrid_live import seed, live_app, ha_api


def main():
    out = Path('../scratch/record-review')
    out.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    assert served
    albums = [dict(uri=f'library://album/{i}', media_type='album', name=name,
                   subtitle=artist, image=f'http://192.168.1.2/cover/{i}')
              for i, (name, artist) in enumerate([
                  ('Kind of Blue', 'Miles Davis'), ('Blue Train', 'John Coltrane'),
                  ('Time Out', 'Dave Brubeck'), ('Moanin’', 'Art Blakey'),
                  ('Maiden Voyage', 'Herbie Hancock'), ('Night Train', 'Oscar Peterson')])]
    data = {'a':{'favorites':albums[:], 'recent':[]}, 'b':{'favorites':[], 'recent':[]}}
    writes, searches, held = [], [], []
    hold = False
    fail = False
    def reply(route, body, status=200):
        route.fulfill(status=status, content_type='application/json', body=json.dumps(body))
    def shelf(route):
        from urllib.parse import parse_qs, urlparse
        args = parse_qs(urlparse(route.request.url).query)
        if route.request.method == 'GET':
            reply(route, data[args['member_id'][0]])
        elif route.request.method == 'POST':
            body = route.request.post_data_json
            writes.append(body)
            data[body['member_id']]['favorites'].append(body['item'])
            reply(route, {'ok':True})
        else:
            owner, uri = args['member_id'][0], args['uri'][0]
            writes.append({'remove':uri,'member_id':owner})
            data[owner]['favorites'] = [item for item in data[owner]['favorites'] if item['uri'] != uri]
            reply(route, {'ok':True})
    def search(route):
        searches.append(route.request.url)
        if hold:
            held.append(route)
        else:
            reply(route, {'groups':[{'type':'album', 'items':albums}], 'total':6}, 503 if fail else 200)
    def play(route):
        body = route.request.post_data_json
        writes.append(body)
        if body.get('member_id'):
            data[body['member_id']]['recent'] = [body['item']]
        reply(route, {'ok':True})
    try:
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
            page.route('**/api/members', lambda r: reply(r, [{'id':'a','name':'Alex'}, {'id':'b','name':'Sam'}]))
            page.route('**/api/ha/media_players', lambda r: reply(r, [dict(entity_id='media_player.living', name='Living room',state='paused',volume_level=.3)]))
            page.route('**/api/music/**', lambda r: reply(r, {}))
            page.route('**/api/music/playlists/editable', lambda r: reply(r, []))
            page.route('**/api/music/favorites*', lambda r: reply(r, {'items':[]}))
            page.route('**/api/music/my**', shelf)
            page.route('**/api/music/search*', search)
            page.route('**/api/music/play', play)
            def art(route):
                # Deterministic test art through the real artwork proxy URL.
                token=urlparse(route.request.url).path.rsplit('/',1)[-1]
                index=int(base64.urlsafe_b64decode(token+'='*((-len(token))%4)).decode().rsplit('/',1)[-1])
                colors=['#17434c','#203d71','#ad6c35','#572c48','#50704a','#252831']
                route.fulfill(content_type='image/svg+xml', body=f'<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240"><rect width="240" height="240" fill="{colors[index]}"/><circle cx="{65+index*20}" cy="160" r="80" fill="#c99556"/><path d="M0 0L240 130V0" fill="#eee0b9"/><text x="14" y="30" font-family="sans-serif" font-size="17" font-weight="bold" fill="#1c2329">{albums[index]["name"]}</text></svg>')
            page.route('**/api/ha/image64/*', art)
            page.goto(served.url('house?compare=living&light=day'), wait_until='domcontentloaded')
            page.wait_for_function('window.chfHouseComparison?.readyMs > 0')
            page.locator('#hybrid-hotspots [data-card="music"]').click()
            page.locator('#radio-library').wait_for(state='visible')
            page.wait_for_function('document.querySelectorAll("#radio-member option").length===3')
            def browse(owner, view='favorites'):
                # The shelf's selectors now live inside the radio screen.
                if page.viewport_size['width'] <= 700:
                    page.locator('#radio-camera [data-radio-camera=radio]').click()
                page.locator('#radio-queue-open').click()
                page.locator('#radio-panel-member').select_option(owner)
                page.locator('#radio-panel-view').select_option(view)
                page.locator('#radio-show-records').click()
            assert page.locator('.record-jacket').count() == 0 and not writes
            browse('a')
            page.locator('.record-jacket').nth(5).wait_for(state='attached')
            assert page.locator('.record-jacket.is-selected').count() == 1
            before = len(writes)
            neighbor = page.get_by_role('button', name='Browse Blue Train', exact=True).bounding_box()
            page.mouse.click(neighbor['x'] + neighbor['width'] * .9, neighbor['y'] + neighbor['height'] * .5)
            assert page.get_by_role('button', name='Play Blue Train', exact=True).is_visible()
            assert len(writes) == before, 'Browsing a spine must not play it'
            page.locator('#radio-records').press('ArrowLeft')
            before = len(writes)
            front = page.locator('.is-selected .record-cover').bounding_box()
            x, y = front['x'] + front['width']*.7, front['y'] + front['height']*.5
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x - 85, y, steps=8)
            page.mouse.up()
            assert page.locator('#radio-records').get_attribute('data-selected') == '1'
            assert len(writes) == before, 'Swiping selects without playing'
            page.locator('#radio-records').press('ArrowLeft')
            assert page.locator('#radio-library').evaluate('el => el.parentElement.id === "house-radio" && getComputedStyle(el,"::after").display === "none"')
            assert page.locator('#house-radio').bounding_box() == page.locator('#hybrid-detail-picture').bounding_box()
            assert 'api/ha/image64/' in page.locator('.record-art').first.get_attribute('src')
            page.locator('#radio-records').press('ArrowRight')
            page.locator('#radio-records').press('ArrowRight')
            assert len(writes)==before, 'Cover-flow browsing must never start playback'
            assert page.locator('.is-selected').get_attribute('data-name')=='Time Out'
            front=page.locator('.is-selected .record-cover').bounding_box()
            scene=page.locator('#hybrid-detail-picture').bounding_box()
            assert .39 < front['height']/scene['height'] < .44, 'Album height must match the photographed shelf records'
            neighbor=page.locator('.record-jacket').nth(1).locator('.record-cover').bounding_box()
            assert .24 < neighbor['width']/front['width'] < .8, 'Side albums must show artwork rather than edge-on strips'
            assert page.locator('.is-selected').evaluate('e=>Math.abs(new DOMMatrix(getComputedStyle(e).transform).m13)<.001 && getComputedStyle(e).transformStyle==="preserve-3d"')
            assert page.locator('.record-back').count()==6
            page.screenshot(path=str(out/'cover-flow-middle-desktop.png'))
            page.locator('#radio-records').press('Home')
            page.screenshot(path=str(out/'records-desktop.png'))
            page.locator('#house-compare-light').select_option('night')
            page.wait_for_selector('#house-radio[data-light="night"]')
            page.screenshot(path=str(out/'records-night-desktop.png'))
            page.locator('#house-compare-light').select_option('day')
            page.wait_for_selector('#house-radio[data-light="day"]')
            page.get_by_role('button', name='Play Kind of Blue', exact=True).click()
            page.wait_for_function('document.getElementById("house-radio").getAttribute("aria-busy")==="false"')
            assert writes[-1]['entity_id'] == 'media_player.living' and writes[-1]['member_id'] == 'a'
            assert writes[-1]['item']['uri'] == albums[0]['uri']
            browse('a', 'recent')
            page.get_by_role('button', name='Play Kind of Blue', exact=True).wait_for()
            browse('b', 'recent')
            page.wait_for_function('document.querySelectorAll(".record-jacket").length===0')
            page.locator('#radio-search-open').click()
            page.locator('#radio-query').fill('Miles Davis')
            page.locator('#radio-query').press('Enter')
            page.locator('.record-jacket').nth(5).wait_for(state='attached')
            page.screenshot(path=str(out/'search-desktop.png'))
            assert 'q=Miles%20Davis' in searches[-1]
            page.locator('#radio-search-close').click()
            page.locator('#radio-queue-open').click()
            page.locator('#radio-panel-view').select_option('search')
            page.locator('#radio-panel-query').fill('Miles Davis')
            page.locator('#radio-panel-search button[type=submit]').click()
            favorite = page.get_by_role('button', name='Favorite Kind of Blue', exact=True)
            favorite.click()
            expect(favorite).to_have_attribute("aria-pressed", "true")
            assert writes[-1]['member_id'] == 'b'
            assert len(data['a']['favorites']) == 6 and len(data['b']['favorites']) == 1
            favorite.click()
            expect(favorite).to_have_attribute("aria-pressed", "false")
            assert data['b']['favorites'] == []
            page.locator('#radio-panel-close').click()
            page.locator('#radio-search-open').click()
            page.locator('#radio-query').fill('Miles Davis')
            page.locator('#radio-query').press('Enter')
            page.locator('.record-jacket').nth(5).wait_for(state='attached')
            page.set_viewport_size({'width':390,'height':844})
            box = page.locator('#radio-query').bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= 390 and box['height'] >= 40, box
            page.screenshot(path=str(out/'search-phone.png'))
            page.locator('#radio-camera [data-radio-camera="records"]').tap()
            page.locator('#radio-records').press('ArrowRight')
            page.wait_for_function('document.getElementById("radio-records").dataset.selected==="1"')
            browse('a')
            page.locator('.record-jacket').nth(5).wait_for(state='attached')
            page.locator('#radio-records').press('ArrowRight')
            page.locator('#radio-records').press('ArrowRight')
            page.screenshot(path=str(out/'records-phone.png'))
            # Superseded and late search responses must never restore stale content.
            page.locator('#radio-camera [data-radio-camera="radio"]').tap()
            page.locator('#radio-search-open').tap()
            hold = True
            page.locator('#radio-query').fill('old')
            page.locator('#radio-query').press('Enter')
            page.wait_for_function('document.getElementById("radio-library-status").textContent.includes("Searching")')
            page.locator('#radio-query').fill('new')
            assert held
            for route in held:
                reply(route, {'groups':[{'type':'track','items':[{'uri':'stale','name':'Stale'}]}]})
            held.clear()
            hold = False
            fail = True
            page.locator('#radio-query').press('Enter')
            page.wait_for_function('document.getElementById("radio-library-status").textContent.includes("could not connect")')
            assert page.locator('.record-jacket').count() == 0
            page.keyboard.press('Escape')
            assert page.locator('#house-radio').is_visible() and not page.locator('#radio-search-form').is_visible()
            page.set_viewport_size({'width':844,'height':390})
            page.locator('#radio-records').press('End')
            page.get_by_role('button', name='Play Night Train', exact=True).click()
            page.wait_for_function('document.getElementById("house-radio").getAttribute("aria-busy")==="false"')
            assert writes[-1]['item']['name'] == 'Night Train'
            page.screenshot(path=str(out/'records-short-screen.png'))
            page.keyboard.press('Escape')
            page.locator('#radio-library').wait_for(state='hidden')
            errors = [e for e in served.errors() if '503 (Service Unavailable)' not in e]
            assert not errors, errors
        print('PASS: personal shelves, proxied cover art, attributed playback, recent records, search, save/remove, stale results, failure, phone geometry, flipping and Escape', flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    main()
