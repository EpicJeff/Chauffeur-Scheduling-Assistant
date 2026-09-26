"""Exercise the real radio UI against deterministic Music Assistant responses.

Run from chauffeur/: python tests/test_house_radio_live.py --out <directory>
No requests reach household speakers. Screenshots include day/night and touch.
"""
import argparse
import json
from pathlib import Path
import tempfile
from test_house_hybrid_live import seed, live_app, ha_api


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default=tempfile.mkdtemp(prefix='radio_review_'))
    out = Path(parser.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    ha_api.get_states = lambda *a, **kw: []
    ha_api.get_state = lambda *a, **kw: None
    served = live_app(seed)
    assert served, 'Playwright is required for radio verification'
    players = [dict(entity_id='media_player.living', name='Living room', state='paused',
                    media_title='Blue in Green', media_artist='Miles Davis', volume_level=.3),
               dict(entity_id='media_player.kitchen', name='Kitchen', state='idle', volume_level=.2)]
    stations = [dict(name='Evening Jazz', uri='library://radio/1', media_type='radio'),
                dict(name='Classical Radio', uri='library://radio/2', media_type='radio')]
    writes, reads, held = [], [], []
    fail = False
    hold_favorites = True
    hold_command = False
    def fulfill(route, data, status=200):
        route.fulfill(status=status, content_type='application/json', body=json.dumps(data))
    def player_list(route):
        reads.append(route.request.url)
        fulfill(route, players)
    def favorites(route):
        if hold_favorites:
            held.append(route)
        else:
            fulfill(route, {'items':stations})
    def command(route):
        body = route.request.post_data_json
        writes.append((route.request.url, body))
        if hold_command:
            held.append(route)
            return
        if fail:
            fulfill(route, {'detail':'Unavailable'}, 503)
            return
        target = next(p for p in players if p['entity_id'] in route.request.url)
        if body['command'] == 'volume_set':
            target['volume_level'] = body['volume']
        else:
            target['state'] = 'playing' if body['command'] == 'play' else 'paused'
        fulfill(route, {'ok':True})
    def play(route):
        body = route.request.post_data_json
        writes.append((route.request.url, body))
        target = next(p for p in players if p['entity_id'] == body['entity_id'])
        station = next(s for s in stations if s['uri'] == body['media_id'])
        target.update(state='playing', media_title=station['name'], media_artist='Music Assistant')
        fulfill(route, {'ok':True})
    def ready(page):
        page.wait_for_function('document.getElementById("house-radio").getAttribute("aria-busy")==="false"')
    def geometry(page):
        for selector, x in (('#radio-power', .1764), ('#radio-volume', .3118), ('#radio-tune', .453)):
            box = page.locator(selector).bounding_box()
            plane = page.locator('#house-radio').bounding_box()
            assert box['width'] >= 44 and box['height'] >= 44, box
            assert 0 <= box['x'] <= page.viewport_size['width'] - box['width'], box
            assert 0 <= box['y'] <= page.viewport_size['height'] - box['height'], box
            assert abs(box['x'] + box['width']/2 - (plane['x'] + plane['width']*x)) < 1
            assert abs(box['y'] + box['height']/2 - (plane['y'] + plane['height']*.584)) < 1
    try:
        with served.browser(reduced_motion='reduce', has_touch=True) as page:
            page.route('**/api/v2/chat/stream*', lambda r: r.fulfill(status=204, body=''))
            page.route('**/api/ha/media_players?*', player_list)
            page.route('**/api/ha/media_players', player_list)
            page.route('**/api/ha/media_players/*/command', command)
            page.route('**/api/music/favorites*', favorites)
            page.route('**/api/music/play', play)
            page.goto(served.url('house?compare=living&light=day'), wait_until='domcontentloaded')
            page.wait_for_function('window.chfHouseComparison?.readyMs > 0')
            assert not reads and not writes, 'No radio connection before entering'
            page.locator('#hybrid-hotspots [data-card="music"]').click()
            page.locator('#house-radio').wait_for(state='visible')
            page.wait_for_function('document.querySelectorAll("#radio-output option").length===4')
            assert not writes
            assert page.locator('#radio-output').input_value() == ''
            page.locator('#radio-output').select_option('media_player.living')
            page.wait_for_function('document.getElementById("radio-title").textContent==="Blue in Green"')
            # Favorites arriving after speaker selection still populate tuning.
            page.wait_for_function('document.getElementById("radio-power").disabled===false')
            assert held
            hold_favorites = False
            for route in held:
                fulfill(route, {'items':stations})
            held.clear()
            page.wait_for_function('document.getElementById("radio-tune").disabled===false')
            assert not page.locator('#hybrid-detail-controls').is_visible()
            page.locator('#radio-power').click()
            page.wait_for_function('document.getElementById("radio-power").getAttribute("aria-pressed")==="true"')
            assert writes[-1][1] == {'command':'play'}
            geometry(page)
            page.screenshot(path=str(out / 'radio-day-desktop.png'))
            page.locator('#house-compare-light').select_option('night')
            page.wait_for_selector('#house-radio[data-light="night"]')
            page.wait_for_function('document.querySelector("img[data-view=music][data-light=night]").naturalWidth > 0')
            page.screenshot(path=str(out / 'radio-night-desktop.png'))
            before = len(writes)
            vol = page.locator('#radio-volume')
            box = vol.bounding_box()
            x, y = box['x']+box['width']/2, box['y']+box['height']/2
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x, y-40, steps=8)
            assert len(writes) == before, 'Do not stream writes during drag'
            page.mouse.up()
            page.wait_for_function('document.getElementById("radio-volume").getAttribute("aria-valuenow")==="50" && document.getElementById("house-radio").getAttribute("aria-busy")==="false"')
            assert len(writes) == before+1 and writes[-1][1] == {'command':'volume_set','volume':.5}
            # A canceled touch gesture sends nothing.
            before = len(writes)
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x, y-20)
            vol.dispatch_event('pointercancel', {'pointerId':1})
            page.mouse.up()
            assert len(writes) == before
            vol.focus()
            vol.press('ArrowRight')
            page.wait_for_function('document.getElementById("radio-volume").getAttribute("aria-valuenow")==="52" && document.getElementById("house-radio").getAttribute("aria-busy")==="false"')
            assert writes[-1][1]['volume'] == .52
            tune = page.locator('#radio-tune')
            before = len(writes)
            tune.press('ArrowRight')
            assert page.locator('#radio-title').inner_text() == 'Classical Radio'
            assert len(writes) == before
            tune.press('Enter')
            page.wait_for_function('document.getElementById("radio-subtitle").textContent==="Music Assistant"')
            ready(page)
            assert len(writes) == before+1
            assert writes[-1][1] == {'entity_id':'media_player.living','media_id':'library://radio/2','media_type':'radio'}
            page.locator('#radio-stations').select_option('0')
            page.wait_for_function('document.getElementById("radio-title").textContent==="Evening Jazz" && document.getElementById("house-radio").getAttribute("aria-busy")==="false"')
            page.set_viewport_size({'width':390,'height':844})
            geometry(page)
            page.screenshot(path=str(out / 'radio-night-phone.png'))
            page.locator('#radio-power').tap()
            page.wait_for_function('document.getElementById("radio-power").getAttribute("aria-pressed")==="false"')
            fail = True
            page.locator('#radio-power').tap()
            page.wait_for_function('document.getElementById("radio-notice").textContent.includes("did not accept")')
            ready(page)
            assert page.locator('#radio-power').get_attribute('aria-pressed') == 'false'
            page.screenshot(path=str(out / 'radio-error-phone.png'))
            fail = False
            # Selection change while a command is outstanding cannot reroute it.
            hold_command = True
            page.locator('#radio-power').tap()
            page.wait_for_function('document.getElementById("house-radio").getAttribute("aria-busy")==="true"')
            page.locator('#radio-output').select_option('media_player.kitchen')
            assert held
            for route in held:
                fulfill(route, {'detail':'late failure'}, 503)
            held.clear()
            hold_command = False
            ready(page)
            assert 'media_player.living' in writes[-1][0]
            assert page.locator('#radio-notice').inner_text() == ''
            # Polling follows external state; a missing selected speaker stays selected.
            players[1].update(state='playing', media_title='External track', media_artist='Other controller')
            page.wait_for_function('document.getElementById("radio-title").textContent==="External track"', timeout=10000)
            players.pop()
            page.wait_for_function('document.getElementById("radio-state").textContent==="SPEAKER UNAVAILABLE"', timeout=10000)
            assert page.locator('#radio-output').input_value() == 'media_player.kitchen'
            assert page.locator('#radio-power').is_disabled()
            page.locator('#hybrid-view-back').tap()
            page.locator('#house-radio').wait_for(state='hidden')
            before = len(reads)
            page.wait_for_timeout(5500)
            assert len(reads) == before, 'Polling must stop on exit'
            errors = [e for e in served.errors() if '503 (Service Unavailable)' not in e]
            assert not errors, errors
        print('PASS: radio API contracts, live playback, volume drag/cancel/keyboard, tuning, delayed favorites, stale writes, failures, speaker loss, touch geometry and polling lifecycle', flush=True)
    finally:
        served.stop()


if __name__ == '__main__':
    main()
